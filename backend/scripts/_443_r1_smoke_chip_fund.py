"""443号R1验证：RAW-2 重算少量股票，核查 pre_feat_cache.chip_fund_ext 六字段（ssrp/asr/concentration/profit_ratio/cyqkl/rsi）

用法（必须用 backend/.venv/bin/python）：
    .venv/bin/python scripts/_443_r1_smoke_chip_fund.py --smoke 5          # 冒烟重算前 5 只
    .venv/bin/python scripts/_443_r1_smoke_chip_fund.py --codes 000002.SZ,600519.SH

背景：443号R1 修复了 data_daemon.py RAW-2 资金筹码扩展字段段的持久化 bug——
  cde.estimate() 返回 4 元组被单变量接收，迭代 numpy 数组抛 TypeError 被静默吞，
  导致 ssrp/asr/concentration/profit_ratio/cyqkl/rsi 全市场 0%。
验证：重算后 pre_feat_cache 最新一行 chip_fund_ext 六字段应非空且 ssrp>0。
"""
import os
import sys
import time
import shutil
import sqlite3
import argparse
import logging
import json

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
for k in ['HTTP_PROXY', 'HTTPS_PROXY', 'ALL_PROXY']:
    os.environ.pop(k, None)

logging.basicConfig(level=logging.INFO, format='%(message)s')
logger = logging.getLogger('443_r1')

CHIP_FIELDS = ('ssrp', 'asr', 'concentration', 'profit_ratio', 'cyqkl', 'rsi')


def _backup(db_path: str) -> str:
    if not os.path.exists(db_path):
        return ''
    stamp = time.strftime('%Y%m%d_%H%M%S')
    bak = f"{db_path}.bak_443_r1_{stamp}"
    shutil.copy2(db_path, bak)
    return bak


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--smoke', type=int, default=0, help='冒烟重算前 N 只（0=全量）')
    ap.add_argument('--codes', default='', help='指定重算代码（逗号分隔），优先于 --smoke')
    ap.add_argument('--no-backup', action='store_true')
    args = ap.parse_args()

    import data_daemon as dd
    dd._ensure_ecm()
    dd._ensure_pd()

    data_dir = os.environ.get('DATA_DIR') or os.path.abspath(
        os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', '..', 'data'))
    compute_db = os.path.join(data_dir, 'duckdb', 'compute_cache.db')

    if args.codes:
        codes = [c.strip() for c in args.codes.split(',') if c.strip()]
    else:
        codes = dd._get_active_codes()
        if not codes:
            logger.error("active 股票池为空，中止")
            return 1
        if args.smoke:
            codes = codes[:args.smoke]
    logger.info(f"[RAW-2] 重算 {len(codes)} 只: {codes[:5]}{'...' if len(codes) > 5 else ''}")

    t0 = time.time()
    dd._precompute_raw_features(codes)
    logger.info(f"[RAW-2] 完成，耗时 {time.time()-t0:.1f}s")

    conn = sqlite3.connect(compute_db)
    latest = conn.execute("SELECT MAX(trade_date) FROM pre_feat_cache").fetchone()[0]
    rows = conn.execute(
        "SELECT ts_code, features_json FROM pre_feat_cache "
        "WHERE ts_code IN ({}) AND trade_date=?".format(','.join('?' * len(codes))),
        codes + [latest]).fetchall()
    conn.close()

    all_ok = True
    for code, fj in rows:
        try:
            chip = json.loads(fj).get('chip_fund_ext') or {}
        except Exception:
            chip = {}
        vals = {k: chip.get(k) for k in CHIP_FIELDS}
        has_real = any(v is not None and v not in (0, 0.0, '') for v in vals.values())
        ssrp_ok = vals.get('ssrp') not in (None, 0, 0.0, '')
        logger.info(f"[核查] {code} chip_fund_ext: {vals}")
        if not (has_real and ssrp_ok):
            all_ok = False
            logger.warning(f"[核查] {code} 六字段仍为空/0，R1 未生效（latest={latest}）")
    logger.info(f"[验证] 样本 {len(rows)}/{len(codes)} 只，latest={latest}，R1 {'PASS' if all_ok else 'FAIL'}")
    return 0 if all_ok else 2


if __name__ == '__main__':
    sys.exit(main())
