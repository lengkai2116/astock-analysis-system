"""
全市场技术指标预计算脚本
=========================
读取 daily_cache → 逐只股票计算 MA/MACD/RSI/KDJ/BOLL → 写入宽表 indicator_ma/indicator_macd/indicator_other
约 5500 只 × 1200 天 × 15 指标，预估耗时 ~30 分钟。
"""
import sys, os, time
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

# 免疫 Claude 代理变量
for k in ['HTTP_PROXY','HTTPS_PROXY','ALL_PROXY','http_proxy','https_proxy','all_proxy']:
    os.environ.pop(k, None)

os.environ['FLASK_APP'] = 'app'
os.environ['FLASK_ENV'] = 'production'

from flask import Flask
from app import create_app
from app.data.enhanced_cache_manager import get_ecm_instance
from app.data.precompute_indicator_manager import PrecomputeIndicatorManager
import pandas as pd
import logging

logging.basicConfig(level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(message)s')
logger = logging.getLogger('precompute')

app = create_app()

with app.app_context():
    ecm = get_ecm_instance()
    mgr = PrecomputeIndicatorManager(ecm)

    # 1. 读取全市场所有 ts_code + 可用天数
    logger.info("读取 daily_cache 股票列表...")
    codes_df = pd.read_sql("""
        SELECT ts_code, COUNT(*) as days
        FROM daily_cache
        GROUP BY ts_code
        HAVING days >= 30
        ORDER BY ts_code
    """, ecm.conn)
    codes = codes_df['ts_code'].tolist()
    total = len(codes)
    logger.info(f"需预计算: {total} 只（已过滤数据不足 30 天的）")

    # 2. 逐只股票预计算
    t_start = time.time()
    ok = 0
    skip = 0

    for idx, ts_code in enumerate(codes, 1):
        try:
            # 读 daily_cache
            df = ecm.get_cached_daily(ts_code)
            if df.empty or len(df) < 30:
                skip += 1
                continue

            df = df.sort_values('trade_date').reset_index(drop=True)

            # 计算并缓存
            success = mgr.precompute_all_indicators(ts_code, df)
            if success:
                ok += 1
            else:
                skip += 1

        except Exception as e:
            logger.warning(f"[{idx}/{total}] {ts_code} 失败: {e}")
            skip += 1

        if idx % 100 == 0 or idx == total:
            elapsed = time.time() - t_start
            rate = idx / elapsed if elapsed > 0 else 0
            logger.info(f"[{idx}/{total}] 成功 {ok}, 跳过 {skip}, "
                        f"耗时 {elapsed:.0f}s, 速率 {rate:.1f}只/s")

            # 每 500 只强制 checkpoint
            if idx % 500 == 0:
                ecm.conn.commit()

    ecm.conn.commit()
    t_elapsed = time.time() - t_start

    # 3. 验证结果（旧 indicator_cache 已拆分为 indicator_ma/indicator_macd/indicator_other 宽表）
    cnt_ma = ecm.conn.execute(
        "SELECT COUNT(*) FROM indicator_ma"
    ).fetchone()[0]
    cnt_macd = ecm.conn.execute(
        "SELECT COUNT(*) FROM indicator_macd"
    ).fetchone()[0]
    cnt_other = ecm.conn.execute(
        "SELECT COUNT(*) FROM indicator_other"
    ).fetchone()[0]
    stocks_with_data = ecm.conn.execute(
        "SELECT COUNT(DISTINCT ts_code) FROM indicator_ma"
    ).fetchone()[0]

    logger.info("=" * 50)
    logger.info(f"预计算完成: {ok} 只成功, {skip} 只跳过")
    logger.info(f"总耗时: {t_elapsed:.0f}s ({t_elapsed/60:.1f}min)")
    logger.info(f"indicator_ma: {cnt_ma} 行, indicator_macd: {cnt_macd} 行, indicator_other: {cnt_other} 行, {stocks_with_data} 只")
    logger.info("=" * 50)
