"""496号随行 C1~C4 日终核验探针（2026-09-29，09-28 管道 16/16 done 后）"""
import json
import sqlite3
import sys

DATA = '/Users/kalence/Desktop/01-A股股票分析系统/data/duckdb'


def q(db, sql, args=()):
    conn = sqlite3.connect(f'{DATA}/{db}')
    try:
        cur = conn.execute(sql, args)
        return cur.fetchall()
    finally:
        conn.close()


print('=== C1: status_snapshot 09-28 entry_zone（K4 回升观察）===')
rows = q('snapshot_cache.db',
         "SELECT COUNT(*), SUM(signals IS NOT NULL AND signals != '' AND signals != '{}'), "
         "SUM(advice_params IS NOT NULL AND advice_params LIKE '%entry_zone%') "
         "FROM status_snapshot WHERE trade_date='2026-09-28'")
print(f'  09-28 行数={rows[0][0]}  signals非空={rows[0][1]}  advice_params含entry_zone键={rows[0][2]}')

# entry_zone 具体非空计数
n_entry = 0
n_target = 0
n_signal = 0
sample = []
for (ap, sig, ts) in q('snapshot_cache.db',
        "SELECT advice_params, signals, ts_code FROM status_snapshot "
        "WHERE trade_date='2026-09-28' AND advice_params IS NOT NULL LIMIT 1000"):
    try:
        d = json.loads(ap)
        ez = d.get('entry_zone')
        tz = d.get('target_zone')
        if ez:
            n_entry += 1
        if tz:
            n_target += 1
    except Exception:
        pass
    if sig and sig not in ('{}', ''):
        n_signal += 1
        if len(sample) < 3:
            sample.append((ts, sig[:80]))
print(f'  (前1000只) entry_zone非空={n_entry}  target_zone非空={n_target}  signals非空={n_signal}')
for ts, s in sample:
    print(f'    {ts}: {s}')

print()
print('=== C2: status_snapshot.signals 落库（全市场）===')
rows = q('snapshot_cache.db',
         "SELECT trade_date, COUNT(*) total, "
         "SUM(CASE WHEN signals IS NOT NULL AND signals NOT IN ('','{}','null') THEN 1 ELSE 0 END) "
         "FROM status_snapshot GROUP BY trade_date ORDER BY trade_date DESC LIMIT 4")
for r in rows:
    print(f'  {r[0]}: {r[2]}/{r[1]} 有 signals')

print()
print('=== C3: pre_feat 09-28 sentiment_phase 分布（ebb→ferment 观察）===')
rows = q('compute_cache.db',
         "SELECT json_extract(features_json, '$.sentiment.sentiment_phase') ph, COUNT(*) "
         "FROM pre_feat_cache WHERE trade_date='2026-09-28' GROUP BY ph ORDER BY 2 DESC")
for ph, c in rows:
    print(f'  sentiment_phase={ph}: {c}')

print()
print('=== C4: pre_feat 09-28 状态机口径（vp_state_label/vp_rule 落库）===')
rows = q('compute_cache.db',
         "SELECT COUNT(*), "
         "SUM(json_extract(features_json, '$.volume_price.vp_state_label') IS NOT NULL), "
         "SUM(json_extract(features_json, '$.volume_price.vp_rule') IS NOT NULL) "
         "FROM pre_feat_cache WHERE trade_date='2026-09-28'")
print(f'  09-28 行数={rows[0][0]}  vp_state_label非空={rows[0][1]}  vp_rule非空={rows[0][2]}')
dist = q('compute_cache.db',
         "SELECT json_extract(features_json, '$.volume_price.vp_state_label') st, COUNT(*) "
         "FROM pre_feat_cache WHERE trade_date='2026-09-28' GROUP BY st ORDER BY 2 DESC LIMIT 8")
for st, c in dist:
    print(f'    vp_state_label={st}: {c}')
