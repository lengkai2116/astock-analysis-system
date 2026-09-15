"""436号 B3 生产刷新：重算 SIG 09-14 + 回填历史空壳（写入开发基准库 snapshot_cache.db）

用法（必须用 backend/.venv/bin/python）：
    .venv/bin/python scripts/_436_recompute_backfill.py recompute [--smoke N]   # 重算 09-14 SIG + 重跑 OUT 透传
    .venv/bin/python scripts/_436_recompute_backfill.py backfill              # 回填历史空壳日（08-26/09-09/09-10/09-11）

安全前提：已备份 snapshot_cache.db.bak_436_20260915；确认无 data_daemon 在运行。
链路：
  - recompute: data_daemon._precompute_strategy_signals(codes) 全市场 SIG（dim_results+dim8 七维）
              → _out_transmit_seven_dim(codes) 让 status_snapshot.one_liner_detail 透传
  - backfill: 扫描历史空壳日，读 dim_results_json → Dim8SummaryEngine.build_seven_dim_report
              重建 seven_dim → UPDATE（不重算维度，纯重建文字）
"""
import os
import sys
import json
import time
import logging

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
for k in ['HTTP_PROXY', 'HTTPS_PROXY', 'ALL_PROXY']:
    os.environ.pop(k, None)

logging.basicConfig(level=logging.INFO, format='%(message)s')
logger = logging.getLogger('436_b3')

HISTORY_SHELL_DATES = ['2026-09-11', '2026-09-10', '2026-09-09', '2026-08-26']


def _mk_engine():
    from app.opportunity_atlas.dimensions.dim8_summary_engine import Dim8SummaryEngine
    return Dim8SummaryEngine()


def recompute(smoke: int = 0):
    """重算 09-14 SIG 全市场 + 重跑 OUT 透传"""
    import data_daemon as dd
    dd._ensure_ecm()
    dd._ensure_pd()

    codes = dd._get_active_codes()
    if smoke > 0:
        codes = codes[:smoke]
    logger.info(f"[recompute] 目标 {len(codes)} 只（{'冒烟 ' + str(smoke) if smoke else '全量'}），最新交易日由 compute_batch 取 MAX(daily_cache)")

    t0 = time.time()

    # 步骤1：SIG 重算（compute_batch + dim8 归集 → 写入 strategy_signal_detail）
    logger.info("[recompute] SIG 重算开始...")
    dd._precompute_strategy_signals(codes)
    logger.info(f"[recompute] SIG 重算完成，耗时 {time.time()-t0:.1f}s")

    # 步骤2：OUT 透传（seven_dim → status_snapshot.one_liner_detail）
    t1 = time.time()
    logger.info("[recompute] OUT 透传开始...")
    dd._out_transmit_seven_dim(codes)
    logger.info(f"[recompute] OUT 透传完成，耗时 {time.time()-t1:.1f}s")
    logger.info("[recompute] ✅ 全部完成")


def backfill():
    """回填历史空壳日：读 dim_results_json → dim8 重建 → UPDATE"""
    from app.data.sharding_manager import sharding_manager
    sc = sharding_manager.get_connection(
        sharding_manager.get_db_for_table('strategy_signal_detail'))
    eng = _mk_engine()

    total_updated = 0
    for d in HISTORY_SHELL_DATES:
        # 取该日 dim_results_json 非空的行（空壳判定：seven_dim 现为空壳或缺）
        rows = sc.execute(
            """SELECT ts_code, dim_results_json, seven_dim_json
               FROM strategy_signal_detail WHERE trade_date=? AND dim_results_json IS NOT NULL""",
            [d]).fetchall()
        upd = 0
        skip_empty = 0
        for ts, dj, sj in rows:
            try:
                obj = json.loads(dj)
                # 已非空壳则跳过（幂等）
                if sj:
                    try:
                        cur = json.loads(sj)
                        if isinstance(cur, dict) and len(cur) >= 6:
                            continue
                    except Exception:
                        pass
                rebuilt = eng.build_seven_dim_report(obj, tags={})
                if not rebuilt:
                    skip_empty += 1
                    continue
                sc.execute(
                    "UPDATE strategy_signal_detail SET seven_dim_json=? WHERE ts_code=? AND trade_date=?",
                    [json.dumps(rebuilt, ensure_ascii=False), ts, d])
                upd += 1
            except Exception as e:
                logger.warning(f"[backfill] {d} {ts} 失败: {e}")
        sc.commit()
        total_updated += upd
        logger.info(f"[backfill] {d}: 回填 {upd} 行（跳过缺失素材 {skip_empty}）")
    sc.close()
    logger.info(f"[backfill] ✅ 共回填 {total_updated} 行")


if __name__ == '__main__':
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument('mode', choices=['recompute', 'backfill'])
    ap.add_argument('--smoke', type=int, default=0)
    args = ap.parse_args()
    if args.mode == 'recompute':
        recompute(smoke=args.smoke)
    else:
        backfill()
