"""426号阶段三：收尾脚本（pre_feat 回补完成后执行，独立于对话/会话）

1. 用修复后的 _precompute_market_stats 重算 08-27~09-11 各交易日 market_stats
   ——回补进程启动时加载的旧版代码存在 _ma20_ratio 恒 0.0 bug，给 08-27/08-31
   等写入过 0.0 版统计，需覆盖为正确值
2. 【可选增强，用户确认】刷新 pre_feat_cache 各日行 features_json 的
   market_stats 快照为权威值——历史行（09-09~11 为 0.5/0.1 兜底假值、
   回补日期为 0.0 版）统一纠正，保证 pre_feat 与 market_stats_cache 一致
3. 验证 pre_feat_cache 每日 ≥5,000 行（§10 阶段三 3.5 检验标准）+ 抽查刷新生效
4. 输出报告到 data/alerts/426_p3_finalize_report.txt

运行：cd backend && .venv/bin/python scripts/_426_phase3_finalize.py
前提：scripts/_426_phase3_prefeat_backfill.py 已跑完（或 checkpoint 覆盖全部 8 日）。
"""
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import data_daemon as dd
from app.data.sharding_manager import sharding_manager

REPORT = os.path.join(os.path.dirname(__file__), '..', '..', 'data', 'alerts', '426_p3_finalize_report.txt')
# 回补的 8 个日期（08-27 曾仅 5 行 + 08-31~09-04 + 09-07/08 整日缺失）
BACKFILL_DATES = ['2026-08-27', '2026-08-31', '2026-09-01', '2026-09-02',
                  '2026-09-03', '2026-09-04', '2026-09-07', '2026-09-08']
MS_KEYS = ['ma20_ratio', 'turnover_percentile', 'limit_ratio',
           'rsi_percentile', 'erp_percentile', 'margin_trend', 'pe_percentile']


def q_shard(table, sql, params=None):
    db = sharding_manager.get_db_for_table(table)
    conn = sharding_manager.get_connection(db)
    return conn.execute(sql, params or []).fetchall()


def main():
    lines = []
    def log(msg):
        print(msg)
        lines.append(msg)

    dd._ensure_ecm()

    # ── 1. 重算 08-27~09-11 各交易日 market_stats（修复后 _ma20_ratio 口径）──
    # 范围取 daily_cache 在 08-27~09-11 区间内的全部交易日（含 08-28、09-09~11
    # 幂等重算），保证每日本文档覆盖的 pre_feat 都有权威 market_stats 可刷。
    log("[1] 重算 market_stats（修复后 _ma20_ratio 口径，08-27~09-11）:")
    _db = sharding_manager.get_db_for_table('daily_cache')
    _conn = sharding_manager.get_connection(_db)
    _days = [r[0] for r in _conn.execute(
        "SELECT DISTINCT trade_date FROM daily_cache "
        "WHERE trade_date BETWEEN '2026-08-27' AND '2026-09-11' ORDER BY trade_date")]
    for d in _days:
        try:
            dd._precompute_market_stats(target_date=d)
        except Exception as e:
            log(f"    {d} 重算失败: {e}")
    rows = q_shard('market_stats_cache',
        "SELECT stat_date, round(ma20_ratio,3), round(turnover_percentile,3), "
        "round(limit_ratio,3), round(rsi_percentile,3), round(erp_percentile,3), "
        "round(margin_trend,3), round(pe_percentile,3) FROM market_stats_cache "
        "ORDER BY stat_date")
    bad = 0
    for r in rows:
        vals = [float(v) for v in r[1:8]]
        flag = 'OK'
        if vals[0] == 0.0:  # ma20_ratio 恒 0 = 疑似旧版残留
            flag = '⚠️ ma20_ratio=0'
            bad += 1
        log(f"    {r[0]}  {vals}  {flag}")

    # ── 1.5 【可选增强】刷新 pre_feat_cache market_stats 快照为权威值 ──
    log("\n[1.5] 刷新 pre_feat_cache market_stats 快照（覆盖 0.5 兜底假值/0.0 旧版）:")
    _pc = sharding_manager.get_connection(sharding_manager.get_db_for_table('pre_feat_cache'))
    auth = {r[0]: r for r in _pc.execute(
        "SELECT stat_date, ma20_ratio, turnover_percentile, limit_ratio, "
        "rsi_percentile, erp_percentile, margin_trend, pe_percentile "
        "FROM market_stats_cache ORDER BY stat_date")}
    total_updated = 0
    for d in sorted(auth):
        s = auth[d]
        correct_ms = {k: float(s[i + 1]) for i, k in enumerate(MS_KEYS)}
        correct_ms['computed_at'] = d
        rows = _pc.execute(
            "SELECT ts_code, features_json FROM pre_feat_cache WHERE trade_date=?",
            [d]).fetchall()
        updates = []
        for ts, j in rows:
            try:
                feats = json.loads(j)
            except Exception:
                continue
            if not isinstance(feats, dict):
                continue
            feats['market_stats'] = correct_ms
            updates.append((json.dumps(feats, ensure_ascii=False), ts, d))
        if updates:
            _pc.executemany(
                "UPDATE pre_feat_cache SET features_json=? WHERE ts_code=? AND trade_date=?",
                updates)
            _pc.commit()
            total_updated += len(updates)
        log(f"    {d}: 刷新 {len(updates)} 行")
    log(f"    合计刷新 {total_updated} 行")

    # ── 2. 验证 pre_feat_cache 每日行数 ──
    log("\n[2] pre_feat_cache 每日行数（≥5000 为通过）:")
    rows = q_shard('pre_feat_cache',
        "SELECT trade_date, COUNT(*) FROM pre_feat_cache WHERE trade_date>='2026-08-27' "
        "GROUP BY trade_date ORDER BY trade_date")
    all_ok = True
    for d in rows:
        ok = d[1] >= 5000
        all_ok = all_ok and ok
        log(f"    {d[0]}: {d[1]} 行  {'✅' if ok else '❌不足5000'}")
    missing = [d for d in BACKFILL_DATES if d not in {r[0] for r in rows}]
    if missing:
        all_ok = False
        log(f"    缺失日期: {missing}（需重跑回补脚本续跑）")

    # ── 2.5 抽查 market_stats 快照已刷新（对比权威值）──
    log("\n[2.5] 抽查 pre_feat market_stats 快照与权威值一致:")
    for d in ['2026-08-27', '2026-08-31', '2026-09-07', '2026-09-11']:
        if d not in auth:
            log(f"    {d}: 无权威值，跳过")
            continue
        row = _pc.execute(
            "SELECT features_json FROM pre_feat_cache WHERE trade_date=? LIMIT 1",
            [d]).fetchone()
        if not row:
            log(f"    {d}: 无 pre_feat 行，跳过")
            continue
        ms = json.loads(row[0]).get('market_stats', {})
        match = abs(float(ms.get('ma20_ratio', -1)) - float(auth[d][1])) < 1e-6
        log(f"    {d}: ma20_ratio 快照={ms.get('ma20_ratio')} 权威={auth[d][1]} "
            f"{'✅' if match else '❌不一致'}")

    # ── 3. 结论 ──
    verdict = 'PASS' if all_ok and bad == 0 else 'CHECK'
    log(f"\n[结论] {verdict}（pre_feat 全达标={'是' if all_ok else '否'}，"
        f"market_stats 无 0.0 残留={'是' if bad == 0 else '否'}，"
        f"快照刷新 {total_updated} 行）")
    os.makedirs(os.path.dirname(REPORT), exist_ok=True)
    with open(REPORT, 'w') as f:
        f.write('\n'.join(lines) + '\n')
    log(f"[报告] {REPORT}")


if __name__ == '__main__':
    main()
