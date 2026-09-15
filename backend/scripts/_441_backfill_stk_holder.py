"""441号 B补采：stk_holder 深市主板缺口补采（写入 history_cache.db）

用法（必须用 backend/.venv/bin/python）：
    .venv/bin/python scripts/_441_backfill_stk_holder.py --smoke N   # 冒烟补采 N 只
    .venv/bin/python scripts/_441_backfill_stk_holder.py            # 全量补采缺口票

前提：
  - 已备份 history_cache.db.bak_441_20260915
  - 确认无 data_daemon 进程
缺口判定：09-14 SIG 目标票（剔除指数后）∩ 无 stk_holder_cache 记录 = 待补票。
链路：provider.get_stk_holdernumber(code) => cache_stk_holder_data(df)（复用 daemon 单只补采路径）。
"""
import os
import sys
import time
import logging

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
for k in ['HTTP_PROXY', 'HTTPS_PROXY', 'ALL_PROXY']:
    os.environ.pop(k, None)

logging.basicConfig(level=logging.INFO, format='%(message)s')
logger = logging.getLogger('441_B')


def _get_ecm():
    from app.data.enhanced_cache_manager import get_ecm_instance
    return get_ecm_instance()


def _get_provider():
    from app.data.tushare_provider import TushareProvider
    return TushareProvider()


def _gap_codes():
    """09-14 SIG 目标票（剔除指数）∩ 无 stk_holder_cache 记录 = 待补缺口票"""
    from app.data.sharding_manager import sharding_manager as sm
    import data_daemon as dd
    db_sd = sm.get_db_for_table('strategy_signal_detail')
    db_sh = sm.get_db_for_table('stk_holder_cache')
    sig = set(r[0] for r in sm.get_connection(db_sd).execute(
        "SELECT DISTINCT ts_code FROM strategy_signal_detail WHERE trade_date='2026-09-14'").fetchall())
    # 剔除指数（对齐 _get_active_codes 441号A判据）
    excl = set(dd.BROAD_INDEX_CODES) | set(dd.SW_INDEX_CODES)
    sig = {c for c in sig if c not in excl and not c.endswith('.SI') and not c.startswith('399')}
    sh = set(r[0] for r in sm.get_connection(db_sh).execute(
        "SELECT DISTINCT ts_code FROM stk_holder_cache").fetchall())
    return sorted(sig - sh)


def run(smoke: int = 0):
    import pandas as pd
    ecm = _get_ecm()
    provider = _get_provider()
    codes = _gap_codes()
    if smoke > 0:
        codes = codes[:smoke]
    logger.info(f"[B] 目标 {len(codes)} 只缺口（{'冒烟 ' + str(smoke) if smoke else '全量'}）")
    ok = fail = 0
    t0 = time.time()
    for i, code in enumerate(codes, 1):
        try:
            raw = provider.get_stk_holdernumber(code)
            if raw:
                df = pd.DataFrame(raw)
                for col in ['end_date', 'ann_date']:
                    if col in df.columns:
                        df[col] = pd.to_datetime(df[col]).dt.date
                ecm.cache_stk_holder_data(df)
                ok += 1
                if i % 50 == 0 or smoke:
                    logger.info(f"  [{i}/{len(codes)}] {code} ✅ {len(df)} 行")
            else:
                fail += 1
                logger.warning(f"  {code}: get_stk_holdernumber 空返回")
        except Exception as e:
            fail += 1
            logger.warning(f"  {code}: 失败 {e}")
        if not smoke and i % 100 == 0:
            logger.info(f"  进度 {i}/{len(codes)}（ok={ok} fail={fail}）已用 {time.time()-t0:.0f}s")
    logger.info(f"[B] 完成：成功 {ok}，失败/空 {fail}，总耗时 {time.time()-t0:.1f}s")


if __name__ == '__main__':
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument('--smoke', type=int, default=0)
    args = ap.parse_args()
    run(smoke=args.smoke)
