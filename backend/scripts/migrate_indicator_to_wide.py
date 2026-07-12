"""
迁移 indicator_cache 从 EAV 格式到宽表格式
==========================================
读取旧 indicator_cache (85M 行 EAV) → 按 (ts_code, trade_date) 聚合
→ 写入 indicator_ma / indicator_macd / indicator_other 宽表

幂等：宽表已有数据则跳过对应股票（INSERT OR REPLACE 覆盖）
可中断：已在宽表中的股票自动跳过（断点续传）
"""
import sys, os, time
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

for k in ['HTTP_PROXY','HTTPS_PROXY','ALL_PROXY','http_proxy','https_proxy','all_proxy']:
    os.environ.pop(k, None)

os.environ['FLASK_APP'] = 'app'
os.environ['FLASK_ENV'] = 'production'

from app import create_app
from app.data.enhanced_cache_manager import get_ecm_instance
import pandas as pd
import logging

logging.basicConfig(level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(message)s')
logger = logging.getLogger('migrate')

app = create_app()

with app.app_context():
    ecm = get_ecm_instance()

    # 1. 获取所有在旧表中有数据的股票
    codes = [r[0] for r in ecm.conn.execute(
        "SELECT DISTINCT ts_code FROM indicator_cache ORDER BY ts_code"
    ).fetchall()]

    # 2. 断点续传：检查哪些股票已在宽表中
    done_codes = set()
    try:
        done_codes = {r[0] for r in ecm.conn.execute(
            "SELECT DISTINCT ts_code FROM indicator_ma"
        ).fetchall()}
    except Exception:
        pass

    pending = [c for c in codes if c not in done_codes]
    total = len(pending)
    logger.info(f"共 {len(codes)} 只股票，{len(done_codes)} 只已迁移，"
                f"{total} 只待迁移")

    if not pending:
        logger.info("全部已迁移，跳过")
        sys.exit(0)

    # 3. 逐只股票迁移
    t_start = time.time()
    for idx, ts_code in enumerate(pending, 1):
        try:
            # 读取 EAV 数据
            rows = ecm.conn.execute(
                "SELECT trade_date, indicator_name, value "
                "FROM indicator_cache WHERE ts_code = ? ORDER BY trade_date",
                [ts_code]
            ).fetchall()
            if not rows:
                continue

            # 转为 wide DataFrame
            records = [(r[0], r[1], r[2]) for r in rows]
            df = pd.DataFrame(records, columns=['trade_date', 'indicator_name', 'value'])
            wide = df.pivot_table(index='trade_date', columns='indicator_name',
                                  values='value', aggfunc='first').reset_index()

            # 写入宽表（cache_indicators_wide 会根据列名自动分发到 3 张表）
            wide['ts_code'] = ts_code
            ecm.cache_indicators_wide(ts_code, wide)

            if idx % 200 == 0 or idx == total:
                elapsed = time.time() - t_start
                logger.info(f"[{idx}/{total}] {ts_code} 迁移完成, "
                            f"耗时 {elapsed:.0f}s")
        except Exception as e:
            logger.warning(f"[{idx}/{total}] {ts_code} 迁移失败: {e}")

    # 4. 验证
    new_ma = ecm.conn.execute(
        "SELECT COUNT(*) FROM indicator_ma"
    ).fetchone()[0]
    new_macd = ecm.conn.execute(
        "SELECT COUNT(*) FROM indicator_macd"
    ).fetchone()[0]
    new_other = ecm.conn.execute(
        "SELECT COUNT(*) FROM indicator_other"
    ).fetchone()[0]
    old_cnt = ecm.conn.execute(
        "SELECT COUNT(*) FROM indicator_cache"
    ).fetchone()[0]

    t_elapsed = time.time() - t_start
    total_wide = new_ma + new_macd + new_other

    logger.info("=" * 60)
    logger.info(f"迁移完成!")
    logger.info(f"  宽表总量: {total_wide} 行（MA:{new_ma}, MACD:{new_macd}, Other:{new_other}）")
    logger.info(f"  旧表: {old_cnt} 行（可删除以释放空间）")
    if total_wide > 0:
        logger.info(f"  压缩比: {old_cnt / total_wide:.1f}x")
    logger.info(f"  耗时: {t_elapsed:.0f}s ({t_elapsed/60:.1f}min)")
    logger.info("=" * 60)
