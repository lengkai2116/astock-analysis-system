"""494号 批次2 探针（只读）：R-1 冰点末期「市场级温度回升」可达性与影响面

背景：493 原 gate 用**个股级** right_side_confirm，而冰点 gate 是**市场级** sentiment_phase
→ 全市场 ice 样本 0 → 组合 **0 可达**（规则空转）。494 改成「市场级温度回升」后：
  ice AND mkt_temp ≥ ICE_RECOVERY_TEMP(35)

本探针（真实数据，只读）：
  1. R-9 取数可得性：raw pre_feat `sentiment.limit_up_count/sealing_rate` 与
     `market_stats.ma20_ratio` 覆盖率；
  2. 当前 phase 分布 + 各股市场级温度分布（真实输入）；
  3. **构造 ice**：以真实市场级输入（sentiment_pool 封板率/涨停家数 + market_stats 广度）
     代入 `ice` 阶段 → 计算市场级温度、判定是否回升 → 证明规则**可达**（对比 493 的 0）；
  4. 真链 `_apply_l0`：ice + 冷（真冰点）→ cap 0.10；ice + 回升 → cap 0.60 + basis 附注。

不依赖 DataManager（stub dm），只读分库 → 可与 daemon 并存。
用法：backend/.venv/bin/python backend/scripts/_494_batch2_ice_recovering_probe.py
"""
import glob
import json
import os
import sqlite3
import sys
from collections import Counter

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
for k in ['HTTP_PROXY', 'HTTPS_PROXY', 'ALL_PROXY']:
    os.environ.pop(k, None)

from app.opportunity_atlas.emotion_temperature import market_level_temperature  # noqa: E402
from app.opportunity_atlas.status_engine import (  # noqa: E402
    ICE_RECOVERY_TEMP,
    StatusEngine,
    _normalize_emotion_phase,
)

COMPUTE_DB = os.path.join(os.path.dirname(__file__), '..', '..', 'data', 'duckdb', 'compute_cache.db')


def _q(db, sql, args=()):
    c = sqlite3.connect(f'file:{db}?mode=ro', uri=True)
    try:
        return c.execute(sql, args).fetchall()
    finally:
        c.close()


def _market_level_real_inputs(target_date: str = None):
    """市场级真值：封板率/涨停家数（sentiment_pool_cache）+ 广度（market_stats_cache）

    target_date 指定则取该交易日（与 pre_feat 对齐），否则取最新。
    """
    out = {}
    for p in glob.glob(os.path.join(os.path.dirname(__file__), '..', '..', 'data', 'duckdb', '*.db')):
        try:
            r = _q(p, "SELECT COUNT(*) FROM sqlite_master WHERE type='table' AND name='sentiment_pool_cache'")
            if not r or not r[0][0]:
                continue
            d = target_date or _q(p, "SELECT MAX(trade_date) FROM sentiment_pool_cache")[0][0]
            up = _q(p, "SELECT COUNT(*) FROM sentiment_pool_cache WHERE trade_date=? AND limit_type='up'", [d])[0][0]
            zha = _q(p, "SELECT COUNT(*) FROM sentiment_pool_cache WHERE trade_date=? AND limit_type='zha'", [d])[0][0]
            if not up:
                continue
            out['date'] = d
            out['limit_up_count'] = up
            if up + zha > 0:
                out['sealing_rate'] = round(up / (up + zha) * 100, 1)
        except Exception:
            pass
    ms = _q(COMPUTE_DB, "SELECT stat_date, ma20_ratio FROM market_stats_cache ORDER BY stat_date DESC LIMIT 1")
    if ms:
        out['ms_date'] = ms[0][0]
        out['breadth'] = float(ms[0][1])
    return out


def main():
    rows = _q(COMPUTE_DB,
              "SELECT features_json FROM pre_feat_cache WHERE features_json IS NOT NULL "
              "AND trade_date=(SELECT MAX(trade_date) FROM pre_feat_cache)")
    td = _q(COMPUTE_DB, "SELECT MAX(trade_date) FROM pre_feat_cache")[0][0]
    print(f'### 494 批次2 探针（R-1 冰点末期市场级升温） trade_date={td}  n={len(rows)}')

    real = _market_level_real_inputs(td)
    print('\n--- 市场级真值（直读源）---')
    print(f'  sentiment_pool({real.get("date")}): limit_up={real.get("limit_up_count")} '
          f'sealing={real.get("sealing_rate")}%')
    print(f'  market_stats({real.get("ms_date")}): breadth(ma20_ratio)={real.get("breadth")}')

    phase_cnt = Counter()
    sent_lu = sent_sr = ms_br = 0
    temps_real = []
    n = 0
    for (fj,) in rows:
        try:
            f = json.loads(fj)
        except Exception:
            continue
        n += 1
        tags = {k: v for g, gd in f.items() if isinstance(gd, dict) and g != 'market_stats'
                for k, v in gd.items() if v is not None}
        phase_cnt[_normalize_emotion_phase(tags)] += 1
        sent = f.get('sentiment') or {}
        ms = f.get('market_stats') or {}
        if sent.get('limit_up_count') is not None:
            sent_lu += 1
        if sent.get('sealing_rate') is not None:
            sent_sr += 1
        if ms.get('ma20_ratio') is not None:
            ms_br += 1
        temps_real.append(market_level_temperature(
            phase_cnt and _normalize_emotion_phase(tags),
            sent.get('limit_up_count'), sent.get('sealing_rate'),
            ms.get('ma20_ratio')))

    print('\n--- R-9 取数可得性 ---')
    print(f'  raw sentiment.limit_up_count : {sent_lu}/{n}')
    print(f'  raw sentiment.sealing_rate   : {sent_sr}/{n}')
    print(f'  raw market_stats.ma20_ratio  : {ms_br}/{n}')
    print('\n--- phase 分布 ---')
    for k, v in phase_cnt.most_common():
        print(f'  {k}: {v}')

    # 构造 ice：真实市场级输入（涨停/封板/广度）× ice 阶段
    print('\n--- 构造 ice（真实市场级输入 × ice 阶段）---')
    t_ice_real = market_level_temperature('ice', real.get('limit_up_count'),
                                          real.get('sealing_rate'), real.get('breadth'))
    _real_breadth = real.get('breadth')
    t_ice_cold = market_level_temperature('ice', 0, 0.0, 0.20)
    print(f'  ice + 真实热度(涨停{real.get("limit_up_count")}/封板{real.get("sealing_rate")}%/广度{_real_breadth:.3f})'
          f' → mkt_temp={t_ice_real}  回升(≥{ICE_RECOVERY_TEMP})={t_ice_real >= ICE_RECOVERY_TEMP}')
    print(f'  ice + 真冰点(涨停0/封板0%/广度0.20)                → mkt_temp={t_ice_cold}  '
          f'回升={t_ice_cold >= ICE_RECOVERY_TEMP}')

    # 真链 _apply_l0（stub dm）
    se = StatusEngine(dm=object())
    tag_ice_real = {'sentiment_phase': 'ice', 'limit_up_count': real.get('limit_up_count'),
                    'sealing_rate': real.get('sealing_rate'), 'breadth': real.get('breadth'),
                    'right_side_confirm': '否决'}
    l0_hi = se._apply_l0('T.SZ', tag_ice_real, {})
    l0_lo = se._apply_l0('T.SZ', {'sentiment_phase': 'ice', 'limit_up_count': 0,
                                 'sealing_rate': 0.0, 'breadth': 0.20,
                                 'right_side_confirm': '强确认'}, {})
    print('\n--- 真链 _apply_l0 ---')
    print(f'  ice + 热度已起 → cap={l0_hi["emotion_position_cap"]} '
          f'phase={l0_hi.get("emotion_phase")} basis={l0_hi.get("emotion_recovering_basis")}')
    print(f'  ice + 真冰点   → cap={l0_lo["emotion_position_cap"]} phase={l0_lo.get("emotion_phase")}')
    print('\n--- 结论 ---')
    print('  493（个股级 right_side_confirm）在 ice=0 全市场下可达数 = 0（空转）')
    print(f'  494（市场级温度回升）ice 场景可达：真热度 {t_ice_real >= ICE_RECOVERY_TEMP}，'
          f'真冰点 {t_ice_cold >= ICE_RECOVERY_TEMP}（符合预期：冷则不放、热则放）')


if __name__ == '__main__':
    main()
