"""532号 批次4：RAW-2E 历史回算 + 阈值分位校准。

口径（2026-10-21 拍板）：
  - 分维回算：D1/D3/D5 250 日；D2 受 moneyflow 覆盖限制（当前 60 日）；
    D4 受 limit_detail 限制（当前 120 日）；缺失维度由引擎按可用维度重归一。
  - 阈值分位校准：RPS 用 P90/P95；涨停/炸板/成交额/拥挤度用 P95；
    零膨胀指标（涨停/炸板）只在 >0 样本内取分位；样本 < --min-sample 保持初值。
  - 默认 dry-run（不写库、不改 yaml）；`--write` 才落库，`--write --calibrate` 才回写 yaml。

用法（写库前必须先停 data_daemon 与看守）：
  PYTHONPATH=backend python backend/scripts/_532_backfill_sector_heat_dim.py --days 250 --dry-run
  PYTHONPATH=backend python backend/scripts/_532_backfill_sector_heat_dim.py --days 250 --dry-run \
      --report backend/logs/532_batch4_calibration.json
  PYTHONPATH=backend python backend/scripts/_532_backfill_sector_heat_dim.py --days 250 --write --calibrate
"""
from __future__ import annotations

import argparse
import copy
import json
import math
import os
import re
import sys
import time
from collections import Counter
from datetime import datetime
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / 'backend'))

CONFIG_PATH = ROOT / 'backend' / 'config' / 'sector_heat.yaml'

# key -> (source field, quantile, clamp, digits, nonzero_only)
_CALIB = {
    'rps_very_strong': ('rps_20', 0.90, (70.0, 99.0), 2, False),
    'rps120_overheat': ('rps_120', 0.95, (80.0, 99.5), 2, False),
    'limit_up_ratio': ('limit_up_ratio', 0.95, (1.0, 15.0), 2, True),
    'zhaban_ratio': ('zhaban_ratio', 0.95, (10.0, 80.0), 2, True),
    'amount_share': ('amount_share', 0.95, (5.0, 40.0), 2, False),
    'crowding_overheat': ('dim_sentiment', 0.95, (50.0, 99.0), 2, False),
}

_COLS = [
    'stat_date', 'industry',
    'ret_20', 'ret_60', 'ret_120',
    'rps_20', 'rps_60', 'rps_120', 'rps_resonance',
    'excess_20', 'excess_60',
    'main_net_5d', 'fund_ratio', 'margin_growth_5d',
    'north_net_5d', 'etf_share_chg_5d',
    'vol_ratio_5d', 'breakout_20d', 'vp_state', 'vp_score',
    'limit_up_ratio', 'zhaban_ratio', 'max_board_height',
    'amount_share', 'fd_amount_ratio', 'open_times_avg',
    'up_ratio', 'med_vs_mean', 'rps_high_ratio',
    'dim_rs', 'dim_fund', 'dim_vp', 'dim_sentiment', 'dim_breadth',
    'quality_score', 'stage', 'heat_rank',
    'flags_json', 'coverage_json', 'calc_version',
]


def _trade_dates(ecm, days: int, end: str | None = None) -> list[str]:
    sql = "SELECT DISTINCT trade_date FROM daily_cache WHERE ts_code LIKE '801%.SI'"
    params: list = []
    if end:
        sql += " AND trade_date <= ?"
        params.append(str(end))
    sql += " ORDER BY trade_date DESC LIMIT ?"
    params.append(int(days))
    df = ecm._query_shard('daily_cache', sql, params)
    if df is None or df.empty:
        return []
    return sorted(str(x) for x in df['trade_date'].tolist())


def _quantile(values: list[float], q: float) -> float | None:
    vals = sorted(float(v) for v in values if v is not None and math.isfinite(float(v)))
    if not vals:
        return None
    if len(vals) == 1:
        return vals[0]
    pos = (len(vals) - 1) * q
    lo, hi = int(math.floor(pos)), int(math.ceil(pos))
    if lo == hi:
        return vals[lo]
    return vals[lo] + (vals[hi] - vals[lo]) * (pos - lo)


def _stats(values: list[float]) -> dict:
    vals = [float(v) for v in values if v is not None and math.isfinite(float(v))]
    if not vals:
        return {'n': 0}
    return {
        'n': len(vals),
        'min': round(min(vals), 3),
        'p10': round(_quantile(vals, 0.10), 3),
        'p50': round(_quantile(vals, 0.50), 3),
        'p90': round(_quantile(vals, 0.90), 3),
        'p95': round(_quantile(vals, 0.95), 3),
        'max': round(max(vals), 3),
    }


def _calibrate(all_rows: list[dict], cfg: dict, min_sample: int,
               keep: list[str] | None = None) -> tuple[dict, dict]:
    old_th = dict(cfg.get('thresholds') or {})
    new_th = dict(old_th)
    keep_set = set(keep or [])
    report = {}
    for key, (field, q, clamp, digits, nonzero) in _CALIB.items():
        vals = [r.get(field) for r in all_rows]
        vals = [v for v in vals if v is not None]
        if nonzero:
            vals = [v for v in vals if v > 0]
        st = _stats(vals)
        old = old_th.get(key)
        if key in keep_set:
            report[key] = {**st, 'quantile': q, 'old': old, 'new': old,
                           'status': 'kept'}
            continue
        if len(vals) < min_sample:
            report[key] = {**st, 'quantile': q, 'old': old, 'new': old,
                           'status': 'insufficient'}
            continue
        val = _quantile(vals, q)
        val = max(clamp[0], min(clamp[1], val))
        val = round(val, digits)
        new_th[key] = val
        report[key] = {**st, 'quantile': q, 'old': old, 'new': val,
                       'status': 'calibrated'}
    return new_th, report


def _coverage_counts(all_rows: list[dict]) -> dict:
    keys = ('d1', 'd2', 'd3', 'd4', 'd5', 'limit_detail', 'rps', 'etf')
    c = Counter()
    for r in all_rows:
        cov = r.get('coverage') or {}
        for k in keys:
            if cov.get(k):
                c[k] += 1
    return dict(c)


def _stage_impact(by_date: dict[str, list[dict]], cfg_new: dict) -> tuple[dict, dict, int]:
    from app.engine.framework.sector_heat_composite import compute

    old_c, new_c = Counter(), Counter()
    changed = 0
    for rows in by_date.values():
        old_c.update(r.get('stage', 'neutral') for r in rows)
        rec = compute(copy.deepcopy(rows), cfg_new)
        new_c.update(r.get('stage', 'neutral') for r in rec)
        old_map = {r.get('industry'): r.get('stage') for r in rows}
        changed += sum(1 for r in rec if old_map.get(r.get('industry')) != r.get('stage'))
    return dict(old_c), dict(new_c), changed


def _write_rows(ecm, stat_date: str, rows: list[dict]) -> None:
    from app.data.sharding_manager import sharding_manager

    db = sharding_manager.get_db_for_table('sector_heat_dim_cache')
    conn = sharding_manager.get_connection(db)
    lock = sharding_manager.get_write_lock(db)
    vals = [
        (
            stat_date, r.get('industry'),
            r.get('ret_20'), r.get('ret_60'), r.get('ret_120'),
            r.get('rps_20'), r.get('rps_60'), r.get('rps_120'), r.get('rps_resonance'),
            r.get('excess_20'), r.get('excess_60'),
            r.get('main_net_5d'), r.get('fund_ratio'), r.get('margin_growth_5d'),
            r.get('north_net_5d'), r.get('etf_share_chg_5d'),
            r.get('vol_ratio_5d'), r.get('breakout_20d'), r.get('vp_state'), r.get('vp_score'),
            r.get('limit_up_ratio'), r.get('zhaban_ratio'), r.get('max_board_height'),
            r.get('amount_share'), r.get('fd_amount_ratio'), r.get('open_times_avg'),
            r.get('up_ratio'), r.get('med_vs_mean'), r.get('rps_high_ratio'),
            r.get('dim_rs'), r.get('dim_fund'), r.get('dim_vp'),
            r.get('dim_sentiment'), r.get('dim_breadth'),
            r.get('quality_score'), r.get('stage'), r.get('heat_rank'),
            json.dumps(r.get('flags') or [], ensure_ascii=False),
            json.dumps(r.get('coverage') or {}, ensure_ascii=False),
            r.get('calc_version') or '532.1',
        )
        for r in rows
    ]
    with lock:
        conn.execute("DELETE FROM sector_heat_dim_cache WHERE stat_date = ?", [stat_date])
        ph = ', '.join('?' for _ in _COLS)
        conn.executemany(
            f"INSERT OR REPLACE INTO sector_heat_dim_cache ({', '.join(_COLS)}) VALUES ({ph})",
            vals)
        conn.commit()


def _update_yaml(calib: dict, sample_dates: int, sample_rows: int) -> int:
    text = CONFIG_PATH.read_text(encoding='utf-8')
    updated = 0
    for key, info in calib.items():
        if info.get('status') != 'calibrated':
            continue
        pat = re.compile(rf'^(\s*{re.escape(key)}:\s*)[-\d.]+', re.M)
        text, n = pat.subn(lambda m: f"{m.group(1)}{info['new']}", text, count=1)
        if n:
            updated += 1
        else:
            print(f'⚠️ yaml 未找到 thresholds.{key}，跳过')
    text = re.sub(r'\n# 532 批次4 校准元信息.*$', '', text, flags=re.S)
    block = {
        'calibration': {
            'method': 'percentile',
            'sample_dates': sample_dates,
            'sample_rows': sample_rows,
            'generated_at': datetime.now().strftime('%Y-%m-%d %H:%M'),
            'metrics': {
                k: {'n': v.get('n', 0), 'quantile': v.get('quantile'),
                    'old': v.get('old'), 'new': v.get('new'),
                    'status': v.get('status')}
                for k, v in calib.items()
            },
        }
    }
    text = (text.rstrip() + '\n\n# 532 批次4 校准元信息（分位法；样本不足项保持初值）\n'
            + yaml.safe_dump(block, allow_unicode=True, sort_keys=False))
    CONFIG_PATH.write_text(text, encoding='utf-8')
    return updated


def _print_report(calib: dict, old_stage: dict, new_stage: dict,
                  changed: int, dates: list[str], coverage: dict) -> None:
    print('\n=== 阈值校准（分位法）===')
    print('| 指标 | n | p50 | p90 | p95 | 旧值 | 新值 | 状态 |')
    print('|---|---|---|---|---|---|---|---|')
    for k, v in calib.items():
        print(f"| {k} | {v.get('n', 0)} | {v.get('p50', '-')} | {v.get('p90', '-')} | "
              f"{v.get('p95', '-')} | {v.get('old')} | {v.get('new')} | {v.get('status')} |")
    print('\n=== 阶段分布（旧阈值 → 新阈值）===')
    keys = ('mainline', 'pulse', 'overheat', 'cold', 'neutral')
    for k in keys:
        print(f"  {k}: {old_stage.get(k, 0)} → {new_stage.get(k, 0)}")
    print(f"  阶段发生变化: {changed} 个行业-日")
    print(f"\n窗口: {dates[0]} ~ {dates[-1]}（{len(dates)} 个交易日）")
    print('覆盖计数（行业-日）:', coverage)


def main():
    ap = argparse.ArgumentParser(description='532号 批次4：RAW-2E 历史回算 + 分位校准')
    ap.add_argument('--days', type=int, default=250, help='回算交易日数（默认 250）')
    ap.add_argument('--end', default=None, help='截止交易日 YYYY-MM-DD（默认最新）')
    ap.add_argument('--write', action='store_true', help='写库（默认 dry-run）')
    ap.add_argument('--dry-run', action='store_true', help='仅计算不写库（默认行为）')
    ap.add_argument('--calibrate', action='store_true', help='计算分位；配合 --write 回写 yaml')
    ap.add_argument('--min-sample', type=int, default=100, help='分位校准最小样本数')
    ap.add_argument('--keep', nargs='*', default=[],
                    help='保持初值的阈值 key（如 zhaban_ratio）')
    ap.add_argument('--report', default=None, help='可选：校准报告 JSON 输出路径')
    args = ap.parse_args()
    if args.write and args.dry_run:
        ap.error('--write 与 --dry-run 互斥')

    os.environ.setdefault('DATA_DIR', str(ROOT / 'data'))
    os.environ.setdefault('DATA_DAEMON_RUNNING', '1')

    from app.data.enhanced_cache_manager import EnhancedCacheManager
    from app.data.sector_heat_dim import build_sector_heat_rows, load_config
    from app.data.sharding_manager import init_sharding

    init_sharding(os.environ['DATA_DIR'])
    ecm = EnhancedCacheManager()
    dates = _trade_dates(ecm, args.days, args.end)
    if not dates:
        print('❌ 无可用交易日，终止。')
        return 1
    print(f'窗口: {dates[0]} ~ {dates[-1]}（{len(dates)} 个交易日）')
    print('模式:', 'WRITE（写库）' if args.write else 'DRY-RUN（不写库/不改 yaml）')

    cfg = load_config()
    by_date: dict[str, list[dict]] = {}
    skipped = []
    t0 = time.time()
    for i, d in enumerate(dates, 1):
        try:
            stat_date, rows = build_sector_heat_rows(ecm, target_date=d)
        except Exception as e:
            skipped.append({'date': d, 'error': str(e)[:200]})
            print(f'  [{i}/{len(dates)}] {d} ❌ {e}')
            continue
        if not rows:
            skipped.append({'date': d, 'error': 'no rows'})
            print(f'  [{i}/{len(dates)}] {d} ⚠️ 无数据')
            continue
        by_date[d] = rows
        if i % 20 == 0 or i == len(dates):
            print(f'  [{i}/{len(dates)}] {d} ok（{len(rows)} 行业，'
                  f'{time.time() - t0:.1f}s）', flush=True)

    all_rows = [r for rows in by_date.values() for r in rows]
    if not all_rows:
        print('❌ 全部日期无数据，终止。')
        return 1

    coverage = _coverage_counts(all_rows)
    new_th, calib = _calibrate(all_rows, cfg, args.min_sample, keep=args.keep)
    cfg_new = copy.deepcopy(cfg)
    cfg_new['thresholds'] = new_th
    old_stage, new_stage, changed = _stage_impact(by_date, cfg_new)
    _print_report(calib, old_stage, new_stage, changed, list(by_date), coverage)

    if args.report:
        report = {
            'generated_at': datetime.now().isoformat(timespec='seconds'),
            'window': [dates[0], dates[-1]],
            'dates': len(by_date),
            'skipped': skipped,
            'coverage': coverage,
            'stage_old': old_stage,
            'stage_new': new_stage,
            'changed_industry_days': changed,
            'calibration': calib,
            'thresholds_old': cfg.get('thresholds') or {},
            'thresholds_new': new_th,
        }
        rp = Path(args.report)
        rp.parent.mkdir(parents=True, exist_ok=True)
        rp.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
        print(f'\n报告已写入: {rp}')

    if not args.write:
        print('\nDRY-RUN 完成：未写库、未改 yaml。确认后再加 --write。')
        return 0

    if args.calibrate:
        # 校准后按新阈值重算，避免 DB 仍存旧阈值算出的 stage/quality
        from app.engine.framework.sector_heat_composite import compute
        by_date = {d: compute(copy.deepcopy(rows), cfg_new)
                   for d, rows in by_date.items()}
        all_rows = [r for rows in by_date.values() for r in rows]
        print(f'\n已按校准后阈值重算 {len(by_date)} 个交易日')

    for d, rows in by_date.items():
        _write_rows(ecm, d, rows)
    print(f'\n✅ 已写库: {len(by_date)} 个交易日 / {len(all_rows)} 行业-日')

    if args.calibrate:
        n = _update_yaml(calib, len(by_date), len(all_rows))
        print(f'✅ 已回写 yaml: {n} 个阈值（样本不足项保持初值）')
    else:
        print('ℹ️ 未回写 yaml（需同时加 --calibrate）。')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
