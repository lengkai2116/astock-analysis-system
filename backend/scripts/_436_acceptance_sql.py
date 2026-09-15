"""436号 §5.4 只读验收查询（V1-V4）——只读，不写任何库

用 backend/.venv/bin/python 运行：
    .venv/bin/python scripts/_436_acceptance_sql.py [trade_date]

对齐方案 §5.4：
  V1 键分布：空壳占比应趋近 0（若未跑生产 SIG，仍为旧两键 → 预期空壳）
  V2 七维完整率：含 signal 与 fund_chip 的比例
  V3 灯色分化：V1 基础上看 light 是否仍单一 yellow（旧数据预期单一）
  V4 OUT 透传率：one_liner_detail 非空占比
"""
import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

for k in ['HTTP_PROXY', 'HTTPS_PROXY', 'ALL_PROXY']:
    os.environ.pop(k, None)


def _conn():
    from app.data.sharding_manager import sharding_manager
    return sharding_manager.get_connection('snapshot_cache.db')


def run(trade_date: str):
    conn = _conn()
    print("════ 436 §5.4 只读验收（trade_date={}）════".format(trade_date))

    # 取 seven_dim_json 非空行,在 Python 侧解析键分布（SQLite 无 json_keys）
    raw_rows = conn.execute(
        """SELECT ts_code, seven_dim_json FROM strategy_signal_detail
           WHERE trade_date=? AND seven_dim_json IS NOT NULL""", [trade_date]
    ).fetchall()
    total = len(raw_rows)

    # V1 键分布
    print("\n── V1 键分布（seven_dim_json 非空）──")
    key_groups: dict = {}
    for _ts, js in raw_rows:
        try:
            obj = json.loads(js)
            keys = tuple(sorted(obj.keys())) if isinstance(obj, dict) else ()
        except Exception:
            keys = ('<invalid>',)
        key_groups[keys] = key_groups.get(keys, 0) + 1
    for keys, cnt in sorted(key_groups.items(), key=lambda kv: -kv[1]):
        print("  {} ({} 行)".format(' '.join(keys), cnt))
    if total == 0:
        print("  该日无 seven_dim_json 非空行（total=0）→ 空壳率无法统计")

    # V2 七维完整率（在 Python 侧统计含 signal 与 fund_chip 的行）
    print("\n── V2 七维完整率（含 signal 与 fund_chip）──")
    full = 0
    for _ts, js in raw_rows:
        try:
            obj = json.loads(js)
            if isinstance(obj, dict) and 'signal' in obj and 'fund_chip' in obj:
                full += 1
        except Exception:
            pass
    sig_nonnull = total
    rate = (full / sig_nonnull) if sig_nonnull else 0.0
    print("  七维完整行: {} / 非空 {} = {:.2f}（判据 ≥0.90）".format(full, sig_nonnull, rate))

    # V3 灯色分化（取前 3 行采样看 light 值）
    print("\n── V3 灯色分化（当日 light 值域采样，前 3 行）──")
    sample = raw_rows[:3]
    lights = set()
    for ts, js in sample:
        try:
            obj = json.loads(js)
            seg_lights = {s.get('light') for s in obj.values() if isinstance(s, dict)}
        except Exception:
            seg_lights = set()
        lights |= seg_lights
        print(f"  {ts}: 段内 lights={seg_lights}")
    print(f"  采样 light 域: {lights}（旧数据=单一 yellow，新=🟢🔴🟡 分化）")

    # V4 OUT 透传率（status_snapshot 当日）
    print("\n── V4 OUT 透传率（status_snapshot 当日 one_liner_detail 非空）──")
    try:
        ss_total, ss_hit = conn.execute(
            """SELECT COUNT(*), SUM(CASE WHEN one_liner_detail IS NOT NULL THEN 1 ELSE 0 END)
               FROM status_snapshot WHERE trade_date=?""", [trade_date]
        ).fetchone()
        out_rate = (ss_hit / ss_total) if ss_total else 0.0
        print(f"  one_liner_detail 非空 {ss_hit} / {ss_total} = {out_rate:.2f}（判据 ≥0.90）")
    except Exception as e:
        print(f"  status_snapshot 查询失败（可能无当日行）: {e}")

    conn.close()
    print("\n════ 验收完成（本脚本纯只读，未写任何库）════")


if __name__ == '__main__':
    run(sys.argv[1] if len(sys.argv) > 1 else '2026-09-15')
