"""509号 批次1 探针量化（只读，不写库）

Q4 拍板「先量化再修」→ 本探针量化四项行为变更的数据基础：
  1. **signal_strength 量纲域**（#J2/#J3）：
     - 全市场 signal_strength 分布（min/max/分位），确认 0-100 域；
     - 按现状 8/6/4/2 与拟改 80/60/40/20 分级的 A+/A/B/C/D 分布对比。
  2. **consensus_rate 符号分布**（#J7）：
     - status_snapshot 中 consensus_rate 负值（空头共识）占比；
     - 现状 clamp [0,1] 下 final_score=0 的股数（空头被抹除影响面）。
  3. **decay 评分可达性**（#J8）：
     - signal_analyzer decay 各维分数 → overall_score 分布，确认 70-100（broken）不可达；
     - DECAY_LEVELS 各档（healthy/fading/broken）实际可达计数。
  4. **maintenance.status 枚举**（#J4）：
     - strategy_signal_detail 中 maintenance.status 实际枚举（是否含 broken）；
     - reliability_assessor 映射键 'decayed' 命中率（=0 则键错位实证）。

用法（daemon 运行中亦可，只读）：
  backend/.venv/bin/python backend/scripts/_509_b1_probe.py
"""
import json
import os
import sys
from collections import Counter

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
for k in ['HTTP_PROXY', 'HTTPS_PROXY', 'ALL_PROXY']:
    os.environ.pop(k, None)

from app.data.sharding_manager import sharding_manager  # noqa: E402


def q1_signal_strength_distribution():
    """signal_strength 量纲域 + 分级分布（opportunity_tags_cache 为 tag 行式表）"""
    rows = sharding_manager.execute_query(
        'opportunity_tags_cache',
        "SELECT tag_value FROM opportunity_tags_cache "
        "WHERE tag_name='signal_strength' AND tag_value IS NOT NULL", [])
    vals = []
    for (v,) in rows:
        try:
            vals.append(float(v))
        except (TypeError, ValueError):
            pass
    vals.sort()
    n = len(vals)
    print(f"\n=== 1. signal_strength 量纲域（tag 行数 n={n}） ===")
    if n == 0:
        print("  无 signal_strength tag（可能存于他处/未富化）")
        return
    import statistics
    print(f"  min={vals[0]:.2f}  max={vals[-1]:.2f}  mean={statistics.mean(vals):.2f}")
    for q in (0.25, 0.5, 0.75, 0.9, 0.95, 0.99):
        print(f"  p{q*100:.0f}={vals[int((n-1)*q)]:.2f}")

    def _grade_old(v):
        return 'A+' if v >= 8 else 'A' if v >= 6 else 'B' if v >= 4 else 'C' if v >= 2 else 'D'

    def _grade_new(v):
        return 'A+' if v >= 80 else 'A' if v >= 60 else 'B' if v >= 40 else 'C' if v >= 20 else 'D'

    c_old = Counter(_grade_old(v) for v in vals)
    c_new = Counter(_grade_new(v) for v in vals)
    print("  分级分布（现状 8/6/4/2  vs  拟改 80/60/40/20）：")
    for g in ('A+', 'A', 'B', 'C', 'D'):
        print(f"    {g}: 现状 {c_old[g]} ({c_old[g]/n*100:.1f}%)  "
              f"拟改 {c_new[g]} ({c_new[g]/n*100:.1f}%)")


def q2_consensus_sign_distribution():
    """consensus_rate 符号分布（#J7 影响面）"""
    rows = sharding_manager.execute_query(
        'status_snapshot',
        "SELECT consensus_rate, final_score, opportunity_state FROM status_snapshot "
        "WHERE consensus_rate IS NOT NULL", [])
    n = len(rows)
    neg = [r for r in rows if r[0] is not None and float(r[0]) < 0]
    zero_scr = [r for r in rows if r[1] is not None and float(r[1]) == 0.0]
    print(f"\n=== 2. consensus_rate 符号分布（n={n}） ===")
    print(f"  负值（空头共识，现被 clamp 抹除）: {len(neg)} ({len(neg)/n*100:.2f}%)")
    if neg:
        import statistics
        nvals = sorted(float(r[0]) for r in neg)
        print(f"  负值范围 [{nvals[0]:.3f}, {nvals[-1]:.3f}]  均值 {statistics.mean(nvals):.3f}")
    print(f"  final_score==0.0 的股数: {len(zero_scr)} ({len(zero_scr)/n*100:.2f}%)")
    if neg:
        # 空头分桶的 opportunity_state 分布（clamp 后落哪档）
        states = Counter((r[2] or '?') for r in neg)
        print(f"  空头共识股 opportunity_state 分布: {dict(states)}")


def q3_decay_score_distribution():
    """decay overall_score 分布（#J8 可达性）——signal_json judgment.maintenance"""
    rows = sharding_manager.execute_query(
        'strategy_signal_detail',
        "SELECT signal_json FROM strategy_signal_detail WHERE signal_json IS NOT NULL", [])
    scores = []
    statuses = Counter()
    n_signals = 0
    for (sig_json,) in rows:
        try:
            sig = json.loads(sig_json)
        except Exception:
            continue
        if not isinstance(sig, dict):
            continue
        for name, s in sig.items():
            if not isinstance(s, dict):
                continue
            n_signals += 1
            m = ((s.get('judgment') or {}).get('maintenance')) or {}
            if isinstance(m, dict):
                st = m.get('status')
                if st:
                    statuses[st] += 1
                # decay_score 不在 judgment 内 → 从 status_description.decay_detail 文本提取
                sd = s.get('status_description') or {}
                detail = sd.get('decay_detail') or ''
                import re
                mm = re.search(r'(\d+)', detail)
                if mm:
                    scores.append(float(mm.group(1)))
    print(f"\n=== 3. decay 分布（signal_json 条目 n={n_signals}） ===")
    print(f"  judgment.maintenance.status 枚举: {dict(statuses)}")
    if scores:
        import statistics
        s = sorted(scores)
        print(f"  decay_score(来自 decay_detail): n={len(s)} min={s[0]:.0f} max={s[-1]:.0f} "
              f"mean={statistics.mean(s):.1f}")
        for q in (0.5, 0.9, 0.95, 0.99):
            print(f"    p{q*100:.0f}={s[int((len(s)-1)*q)]:.0f}")
        c = Counter('broken(70+)' if v >= 70 else 'fading(40-69)' if v >= 40 else 'healthy(<40)'
                    for v in scores)
        print(f"  按 DECAY_LEVELS 分档: {dict(c)}")
        print(f"  → broken(70-100) 实测可达数 {c.get('broken(70+)', 0)}（#J8 不可达性实证）")


def q4_maintenance_status_enum():
    """maintenance.status 实际枚举 vs reliability_assessor 映射键（dim_results_json）"""
    rows = sharding_manager.execute_query(
        'strategy_signal_detail',
        "SELECT dim_results_json FROM strategy_signal_detail "
        "WHERE dim_results_json IS NOT NULL", [])
    statuses = Counter()
    n = 0
    for (dj,) in rows:
        try:
            dr = json.loads(dj)
        except Exception:
            continue
        sig = (dr or {}).get('signal') or {}
        if not isinstance(sig, dict):
            continue
        m = (sig.get('judgment') or {})
        m = m.get('maintenance') if isinstance(m, dict) else None
        st = m.get('status') if isinstance(m, dict) else None
        if st:
            statuses[st] += 1
            n += 1
    print(f"\n=== 4. maintenance.status 枚举（dim_results.signal.judgment.maintenance，n={n}） ===")
    print(f"  实际枚举: {dict(statuses)}")
    mapping = {'healthy': 0.8, 'fading': 0.5, 'decayed': 0.2}
    hit = sum(v for k, v in statuses.items() if k in mapping)
    miss = sum(v for k, v in statuses.items() if k not in mapping)
    print(f"  reliability_assessor 映射命中 {hit} / 未命中 {miss}（未命中走默认 0.5）")
    print(f"  'decayed' 键命中（应为 0，生产者用 broken）: {statuses.get('decayed', 0)}")


if __name__ == '__main__':
    q1_signal_strength_distribution()
    q2_consensus_sign_distribution()
    q3_decay_score_distribution()
    q4_maintenance_status_enum()
