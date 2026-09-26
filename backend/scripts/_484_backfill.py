"""484号 数据补采回填脚本（cashflow 折旧列+映射修复 / fina 空壳列 / 质押 / 减持）

用法（必须 backend/.venv/bin/python；含真实库写，先停 data_daemon）：
    .venv/bin/python scripts/_484_backfill.py cashflow [--limit N] [--offset M]
    .venv/bin/python scripts/_484_backfill.py fina     [--limit N] [--offset M]
    .venv/bin/python scripts/_484_backfill.py pledge   [--limit N]
    .venv/bin/python scripts/_484_backfill.py holdertrade [--limit N]
    .venv/bin/python scripts/_484_backfill.py verify   # 只读核对回填结果

- cashflow：强制重写最新报告期（绕过 _finance_covers_period 跳过），
  列名映射修复后 cashflow_oper/inv/fin + 折旧列首次真正落库。
- fina：强制重写最新报告期全字段 → fina_indicator_cache roic/roa/ebit/debt_to_assets 回填
  （gross_margin 不回填——Tushare 该字段为毛利额(元)非毛利率%，见 484 方案 §五）。
- pledge：批量最近周五全市场 + 按股全历史。
- holdertrade：按股近 2 年。
"""
import os
import sys
import time
import argparse

import pandas as pd

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
for k in ['HTTP_PROXY', 'HTTPS_PROXY', 'ALL_PROXY']:
    os.environ.pop(k, None)

import logging
logging.basicConfig(level=logging.INFO, format='%(message)s')
logger = logging.getLogger('484')


def _codes_from_daily(limit=None, offset=0):
    """个股宇宙代码列表（market_universe 剔指数），默认全量"""
    from app.data.market_universe import stock_only_sql
    from app.data.sharding_manager import sharding_manager
    pred, params = stock_only_sql()
    conn = sharding_manager.get_connection('market_cache.db')
    sql = f"SELECT DISTINCT ts_code FROM daily_cache WHERE {pred} ORDER BY ts_code"
    codes = [r[0] for r in conn.execute(sql, params).fetchall()]
    if offset:
        codes = codes[offset:]
    if limit:
        codes = codes[:limit]
    return codes


def _provider():
    from app.data.tushare_provider import TushareProvider
    return TushareProvider()


def _ecm():
    from app.data.enhanced_cache_manager import get_ecm_instance
    return get_ecm_instance()


def _throttle(last, interval=0.2):
    """~5/sec 限流（5000 分 500 次/分余量）"""
    dt = time.time() - last
    if dt < interval:
        time.sleep(interval - dt)
    return time.time()


def backfill_cashflow(limit=None, offset=0):
    provider = _provider()
    ecm = _ecm()
    codes = _codes_from_daily(limit, offset)
    ok = 0
    last = time.time()
    for i, code in enumerate(codes, 1):
        try:
            raw = provider.get_cashflow(code)
            if raw:
                import pandas as pd
                df = pd.DataFrame(raw)
                if 'end_date' in df.columns:
                    df['end_date'] = pd.to_datetime(df['end_date']).dt.date
                if 'ann_date' in df.columns:
                    df['ann_date'] = pd.to_datetime(df['ann_date']).dt.date
                ecm.cache_cashflow_data(df)
                ok += 1
        except Exception as e:
            logger.warning(f"  [cashflow] {code} 失败: {e}")
        last = _throttle(last)
        if i % 500 == 0:
            logger.info(f"  [cashflow] 进度 {i}/{len(codes)}")
    logger.info(f"[cashflow] 完成 {ok}/{len(codes)}")


def backfill_fina(limit=None, offset=0):
    """fina 回填须走全字段（provider.get_fina_indicator 只返回 FINA_FIELDS_ORIGINAL
    基础 11 字段，不含 roic/roa/ebit——空壳根因之一）；直接调 ts.pro_api().fina_indicator"""
    import tushare as ts
    pro = ts.pro_api()
    ecm = _ecm()
    codes = _codes_from_daily(limit, offset)
    ok = 0
    last = time.time()
    for i, code in enumerate(codes, 1):
        try:
            raw = pro.fina_indicator(ts_code=code)
            if raw is not None and not raw.empty:
                df = raw.copy()
                if 'end_date' in df.columns:
                    df['end_date'] = pd.to_datetime(df['end_date']).dt.date
                if 'ann_date' in df.columns:
                    df['ann_date'] = pd.to_datetime(df['ann_date']).dt.date
                ecm.cache_fina_indicator_data(df)
                ok += 1
        except Exception as e:
            logger.warning(f"  [fina] {code} 失败: {e}")
        last = _throttle(last)
        if i % 500 == 0:
            logger.info(f"  [fina] 进度 {i}/{len(codes)}")
    logger.info(f"[fina] 完成 {ok}/{len(codes)}")


def backfill_pledge(limit=None, offset=0):
    provider = _provider()
    ecm = _ecm()
    codes = _codes_from_daily(limit, offset)
    ok = 0
    last = time.time()
    for i, code in enumerate(codes, 1):
        try:
            raw = provider.get_pledge_stat(ts_code=code)
            if raw:
                import pandas as pd
                df = pd.DataFrame(raw)
                if 'end_date' in df.columns:
                    df['end_date'] = pd.to_datetime(df['end_date']).dt.date
                ecm.cache_pledge_stat_data(df)
                ok += 1
        except Exception as e:
            logger.warning(f"  [pledge] {code} 失败: {e}")
        last = _throttle(last)
        if i % 500 == 0:
            logger.info(f"  [pledge] 进度 {i}/{len(codes)}")
    logger.info(f"[pledge] 完成 {ok}/{len(codes)}")


def backfill_holdertrade(limit=None, offset=0):
    provider = _provider()
    ecm = _ecm()
    codes = _codes_from_daily(limit, offset)
    ok = 0
    last = time.time()
    for i, code in enumerate(codes, 1):
        try:
            raw = provider.get_stk_holdertrade(code)
            if raw:
                import pandas as pd
                df = pd.DataFrame(raw)
                if 'ann_date' in df.columns:
                    df['ann_date'] = pd.to_datetime(df['ann_date']).dt.date
                ecm.cache_stk_holdertrade_data(df)
                ok += 1
        except Exception as e:
            logger.warning(f"  [holdertrade] {code} 失败: {e}")
        last = _throttle(last)
        if i % 500 == 0:
            logger.info(f"  [holdertrade] 进度 {i}/{len(codes)}")
    logger.info(f"[holdertrade] 完成 {ok}/{len(codes)}")


def verify():
    from app.data.sharding_manager import sharding_manager
    def q(db, sql):
        conn = sharding_manager.get_connection(db)
        return conn.execute(sql).fetchone()

    print("== cashflow_cache（financial）==")
    r = q('financial_cache.db',
          "SELECT COUNT(*) n, SUM(cashflow_oper IS NOT NULL) op, "
          "SUM(depr_fa_coga_dpba IS NOT NULL) depr, SUM(c_pay_acq_const_fiolta IS NOT NULL) capex "
          "FROM cashflow_cache WHERE end_date=(SELECT MAX(end_date) FROM cashflow_cache)")
    print(f"  最新期: 行={r[0]} cashflow_oper={r[1]} depr_fa_coga_dpba={r[2]} capex={r[3]}")

    print("== fina_indicator_cache（financial）==")
    r = q('financial_cache.db',
          "SELECT COUNT(*) n, SUM(roic IS NOT NULL) roic, SUM(roa IS NOT NULL) roa, "
          "SUM(ebit IS NOT NULL) ebit, SUM(debt_to_assets IS NOT NULL) d2a "
          "FROM fina_indicator_cache WHERE end_date=(SELECT MAX(end_date) FROM fina_indicator_cache)")
    print(f"  最新期: 行={r[0]} roic={r[1]} roa={r[2]} ebit={r[3]} debt_to_assets={r[4]}")

    print("== pledge_stat_cache / stk_holdertrade_cache（history）==")
    for t in ['pledge_stat_cache', 'stk_holdertrade_cache']:
        r = q('history_cache.db', f"SELECT COUNT(*) n, COUNT(DISTINCT ts_code) c FROM {t}")
        print(f"  {t}: 行={r[0]} 覆盖股={r[1]}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('phase', choices=['cashflow', 'fina', 'pledge', 'holdertrade', 'verify'])
    ap.add_argument('--limit', type=int, default=None)
    ap.add_argument('--offset', type=int, default=0)
    args = ap.parse_args()

    if args.phase == 'cashflow':
        backfill_cashflow(args.limit, args.offset)
    elif args.phase == 'fina':
        backfill_fina(args.limit, args.offset)
    elif args.phase == 'pledge':
        backfill_pledge(args.limit, args.offset)
    elif args.phase == 'holdertrade':
        backfill_holdertrade(args.limit, args.offset)
    elif args.phase == 'verify':
        verify()


if __name__ == '__main__':
    main()
