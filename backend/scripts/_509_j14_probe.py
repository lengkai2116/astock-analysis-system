"""509号 批次2 #J14 探针量化（只读，不写库）——快速版

#J14 `consensus_engine.compute`：`total_dim_count` 在 `score is None` 检查**前**自增，
    且按 `GROUP_MAPPING` 声明维（13 个）计数，而 `dims_factor`（convert_to_factors 产出）
    实际仅 7 维 → time/position/signal_confirm/finance/event/factor 六维恒缺席却计入
    分母 → neutral_ratio 系统性偏低 → 「中性占比 >0.6 cap 到 0.5」闸门被弱化。

快速版：不跑 StatusEngine.evaluate（全链太慢），只做
  dim_results + pre_feat tags → convert_to_factors → 复算 neutral_ratio 两种口径。
convert_to_factors 是纯函数（dim_results + tags → dims_factor），足够支撑 #J14 量化。

用法（daemon 运行中亦可，只读）：
  backend/.venv/bin/python backend/scripts/_509_j14_probe.py [limit]
"""
import json
import os
import sys
from collections import Counter

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
for k in ['HTTP_PROXY', 'HTTPS_PROXY', 'ALL_PROXY']:
    os.environ.pop(k, None)

from app.data.sharding_manager import sharding_manager  # noqa: E402
from app.opportunity_atlas.consensus_engine import GROUP_MAPPING  # noqa: E402
from app.opportunity_atlas.dim_adapter import convert_to_factors  # noqa: E402


def _calc_nr(dims_factor, count_missing=True):
    """#J14 两种口径的 neutral_ratio"""
    neutral = 0
    total = 0
    for dims in GROUP_MAPPING.values():
        for dim in dims:
            score = dims_factor.get(dim)
            if score is None:
                if count_missing:
                    total += 1  # 现状：缺失维也计入分母
                continue
            total += 1
            if isinstance(score, dict):
                score = score.get('direction', 0)
            try:
                if abs(float(score)) < 1e-9:
                    neutral += 1
            except (TypeError, ValueError):
                pass
    return neutral / max(total, 1)


def main(limit=None):
    from app import create_app
    app = create_app()
    with app.app_context():
        from app.data import DataManager
        dm = DataManager()

        sql = ("SELECT ts_code, dim_results_json FROM strategy_signal_detail "
               "WHERE dim_results_json IS NOT NULL")
        if limit:
            sql += f" LIMIT {int(limit)}"
        rows = sharding_manager.execute_query('strategy_signal_detail', sql, [])

        n = len(rows)
        print(f"=== #J14 中性闸门探针（快速版，convert_to_factors） n={n} ===")

        declared = [d for dims in GROUP_MAPPING.values() for d in dims]
        print(f"\n1. GROUP_MAPPING 声明维 {len(declared)} 个: {declared}")
        missing = ['time', 'position', 'signal_confirm', 'finance', 'event', 'factor']
        print(f"   恒缺失维 {len(missing)} 个: {missing}（声明含但 dims_factor 无键）")

        nr_now = []
        nr_fixed = []
        n_ok = 0
        for code, dj in rows:
            try:
                dr = json.loads(dj)
                tags = dm.get_pre_feat(code) or {}
                if hasattr(tags, 'to_dict'):
                    tags = tags.to_dict()
                dims_factor = convert_to_factors(dr, tags)
            except Exception:
                continue
            if not dims_factor:
                continue
            n_ok += 1
            nr_now.append(_calc_nr(dims_factor, count_missing=True))
            nr_fixed.append(_calc_nr(dims_factor, count_missing=False))

        if n_ok == 0:
            print('  无样本可转换')
            return
        import statistics
        print(f"\n2. 可转换样本 {n_ok}/{n}")
        print(f"   neutral_ratio 均值: 现状 {statistics.mean(nr_now):.3f} → 修复后 {statistics.mean(nr_fixed):.3f}")
        over_now = sum(1 for v in nr_now if v > 0.6)
        over_fixed = sum(1 for v in nr_fixed if v > 0.6)
        print(f"   >0.6 占比: 现状 {over_now}/{n_ok} ({over_now/n_ok*100:.1f}%)"
              f" → 修复后 {over_fixed}/{n_ok} ({over_fixed/n_ok*100:.1f}%)")
        # 中位数/分位
        for q in (0.5, 0.9, 0.99):
            s_now = sorted(nr_now); s_fix = sorted(nr_fixed)
            i = int((n_ok - 1) * q)
            print(f"   p{q*100:.0f}: 现状 {s_now[i]:.3f} → 修复后 {s_fix[i]:.3f}")


if __name__ == '__main__':
    import sys as _s
    _lim = int(_s.argv[1]) if len(_s.argv) > 1 else None
    main(_lim)
