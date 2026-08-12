"""WAL 定期收缩维护脚本（328号 L2）

背景：SQLite WAL 模式下，TRUNCATE 需所有常驻连接关闭（daemon/API 持续持有
stock_cache.db 连接）——运行中无法收缩，历史实测 WAL 膨胀 86G/11.8G/7.6G。

本脚本守护模式：非交易时段 + 管道空闲时，自动执行：
    1. PASSIVE checkpoint 合并可合并帧
    2. TRUNCATE 截断（需无活跃读事务）
    3. 报告收缩前后 WAL 大小

用法：
    # 一次性执行（手动）
    backend/.venv/bin/python backend/wal_maintenance.py --once
    # 守护模式（建议由 start_daemon.sh 或 cron 调用）
    backend/.venv/bin/python backend/wal_maintenance.py --daemon

守护模式判定（每次 tick）：
    - 非交易时段（9:00-15:30 之外）
    - 管道空闲（pipeline_status 无 running 环节）
    - WAL 大小 > 阈值（默认 500MB，防频繁重启 API）
满足则执行收缩（停 API → 收缩 → 重启 API）。
"""
import argparse
import logging
import os
import signal
import sqlite3
import subprocess
import sys
import time
from pathlib import Path

# ── 路径（Windows 兼容：pathlib） ──
PROJECT_ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = Path(os.environ.get('DATA_DIR', PROJECT_ROOT / 'data'))
DB_PATH = DATA_DIR / 'duckdb' / 'stock_cache.db'
WAL_PATH = DATA_DIR / 'duckdb' / 'stock_cache.db-wal'
BACKEND_DIR = PROJECT_ROOT / 'backend'
VENV_PYTHON = BACKEND_DIR / '.venv' / 'bin' / 'python'
LOG_PATH = DATA_DIR / 'logs' / 'wal_maintenance.log'

# 确保日志目录存在（首次运行自动创建）
LOG_PATH.parent.mkdir(parents=True, exist_ok=True)

# ── 配置 ──
SHRINK_THRESHOLD_MB = 500      # WAL 超过此值才收缩（防频繁重启 API）
DAEMON_INTERVAL = 600          # 守护模式检查间隔（10 分钟）
TRADE_START, TRADE_END = 9, 15 # 交易时段（9:00-15:30）

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(message)s',
    handlers=[
        logging.FileHandler(LOG_PATH, encoding='utf-8'),
        logging.StreamHandler(),
    ],
)
logger = logging.getLogger('wal_maintenance')


def wal_size_mb() -> float:
    try:
        return WAL_PATH.stat().st_size / 1024 / 1024
    except OSError:
        return 0.0


def is_market_hours() -> bool:
    now = time.localtime()
    h = now.tm_hour
    return TRADE_START <= h <= TRADE_END


def pipeline_idle() -> bool:
    """管道空闲 = pipeline_status 无 running 环节"""
    try:
        con = sqlite3.connect(str(DB_PATH))
        try:
            row = con.execute(
                "SELECT COUNT(*) FROM pipeline_status WHERE status='running'"
            ).fetchone()
            return (row[0] if row else 0) == 0
        finally:
            con.close()
    except sqlite3.Error as e:
        logger.warning(f"管道状态查询失败: {e}")
        return False


def api_running() -> bool:
    """检查 API 进程（run.py --port 5001）"""
    try:
        import psutil
        for p in psutil.process_iter(['pid', 'cmdline']):
            cmd = ' '.join(p.info.get('cmdline') or [])
            if 'run.py' in cmd and '5001' in cmd:
                return True
        return False
    except Exception:
        # psutil 不可用时用 pgrep 兜底
        r = subprocess.run(['pgrep', '-f', 'run.py.*5001'],
                           capture_output=True, text=True)
        return r.returncode == 0


def _find_processes(pattern: str) -> list:
    """查找匹配 cmdline 的进程 PID 列表"""
    pids = []
    try:
        import psutil
        for p in psutil.process_iter(['pid', 'cmdline']):
            cmd = ' '.join(p.info.get('cmdline') or [])
            if pattern in cmd:
                pids.append(p.pid)
    except Exception:
        r = subprocess.run(['pgrep', '-f', pattern], capture_output=True, text=True)
        pids = [int(x) for x in r.stdout.split() if x.strip()]
    return pids


def stop_processes(patterns: list) -> None:
    """停止匹配的进程（优雅 SIGTERM，等待退出；10s 未退则 SIGKILL）"""
    import psutil
    for pat in patterns:
        for pid in _find_processes(pat):
            try:
                p = psutil.Process(pid)
                p.terminate()
                try:
                    p.wait(timeout=10)
                except psutil.TimeoutExpired:
                    p.kill()
                logger.info(f"已停止 {pat} (PID {pid})")
            except psutil.NoSuchProcess:
                continue
            except Exception as e:
                logger.warning(f"停止 {pat} (PID {pid}) 异常: {e}")


def api_running() -> bool:
    """检查 API 进程（run.py --port 5001）"""
    return len(_find_processes('run.py')) > 0


def start_processes() -> None:
    """重启 daemon + API（与 start.command 一致）"""
    env = dict(os.environ)
    env['DATA_DAEMON_RUNNING'] = '1'
    # daemon 不直接拉起——看守 start_daemon.sh（若在）10s 内自动恢复；
    # 无看守时（人工停的），此处拉起保证服务恢复。
    if not _find_processes('start_daemon.sh'):
        daemon_log = open(DATA_DIR / 'logs' / 'data_daemon.log', 'a', encoding='utf-8')
        if not _find_processes('data_daemon.py'):
            subprocess.Popen(
                [str(VENV_PYTHON), 'data_daemon.py'],
                cwd=str(BACKEND_DIR),
                env=env,
                stdout=daemon_log,
                stderr=daemon_log,
                start_new_session=True,
            )
            logger.info("daemon 已重启（无看守）")
    api_log = open(DATA_DIR / 'logs' / 'api.log', 'a', encoding='utf-8')
    subprocess.Popen(
        [str(VENV_PYTHON), 'run.py', '--port', '5001'],
        cwd=str(BACKEND_DIR),
        env=env,
        stdout=api_log,
        stderr=api_log,
        start_new_session=True,
    )
    logger.info("API 已重启")


def shrink_wal() -> bool:
    """收缩 WAL：PASSIVE 合并 + TRUNCATE 截断（需所有进程连接关闭）"""
    size_before = wal_size_mb()
    logger.info(f"收缩前 WAL: {size_before:.1f}MB")

    try:
        con = sqlite3.connect(str(DB_PATH), timeout=30)
        try:
            r = con.execute('PRAGMA wal_checkpoint(PASSIVE)').fetchone()
            logger.info(f"PASSIVE: busy={r[0]} frames={r[1]} checkpointed={r[2]}")
            time.sleep(1)
            # TRUNCATE 有限重试（3 次；仍 busy 说明有未释放连接，放弃本次）
            for attempt in range(3):
                r = con.execute('PRAGMA wal_checkpoint(TRUNCATE)').fetchone()
                if r[0] == 0:
                    break
                logger.info(f"TRUNCATE 尝试{attempt}: busy={r[0]}")
                time.sleep(5)
        finally:
            con.close()
    except sqlite3.Error as e:
        logger.error(f"收缩失败: {e}")
        return False

    size_after = wal_size_mb()
    logger.info(f"收缩后 WAL: {size_after:.1f}MB")
    if size_after < max(1, size_before * 0.5):
        logger.info("✅ WAL 收缩成功")
        return True
    logger.warning("⚠️ WAL 未充分收缩（可能仍有连接活跃）")
    return False


def maintenance_once() -> bool:
    """执行一次维护：停 daemon+API → 收缩 → 重启 daemon+API"""
    if not api_running() and not _find_processes('data_daemon.py'):
        logger.info("daemon/API 均未运行——仅收缩（无连接冲突）")
        return shrink_wal()
    logger.info("暂停 daemon+API 以收缩 WAL")
    stop_processes(['data_daemon.py', 'run.py'])
    time.sleep(2)  # 等待连接释放
    ok = shrink_wal()
    start_processes()
    return ok


def daemon_loop() -> None:
    """守护模式：非交易时段 + 管道空闲 + WAL 超阈值 → 收缩"""
    logger.info(f"守护模式启动（检查间隔 {DAEMON_INTERVAL}s, 阈值 {SHRINK_THRESHOLD_MB}MB）")
    while True:
        try:
            size = wal_size_mb()
            if size < SHRINK_THRESHOLD_MB:
                logger.debug(f"WAL {size:.0f}MB < 阈值，跳过")
            elif is_market_hours():
                logger.info(f"WAL {size:.0f}MB 超阈值，但交易时段跳过")
            elif not pipeline_idle():
                logger.info(f"WAL {size:.0f}MB 超阈值，但管道运行中跳过")
            else:
                logger.info(f"WAL {size:.0f}MB 超阈值——执行收缩")
                maintenance_once()
        except Exception as e:
            logger.error(f"守护循环异常: {e}")
        time.sleep(DAEMON_INTERVAL)


def main() -> None:
    parser = argparse.ArgumentParser(description='WAL 定期收缩维护')
    parser.add_argument('--once', action='store_true', help='执行一次后退出')
    parser.add_argument('--daemon', action='store_true', help='守护模式')
    args = parser.parse_args()

    if args.daemon:
        daemon_loop()
    else:
        maintenance_once()


if __name__ == '__main__':
    main()
