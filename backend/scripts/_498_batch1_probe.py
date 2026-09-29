"""498号 批次1 验证探针（只读）
#2 ensure_minute_data 分库读修正：#3 三源 volume 归「手」；#12 daemon 通用请求预算解耦
"""
import os, sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
for k in ['HTTP_PROXY', 'HTTPS_PROXY', 'ALL_PROXY']:
    os.environ.pop(k, None)

from app.data.sharding_manager import sharding_manager

print("=== #2 分库读修正验证（ensure_minute_data 改用 _query_shard）===")
# a) 分库读 minute_kline_cache 5min 计数（原直读总库必抛/恒0）
codes = ['600519.SH', '000001.SZ']
for c in codes:
    conn = sharding_manager.get_connection('market_cache.db')
    import pandas as pd
    df = pd.read_sql('SELECT COUNT(*) AS n FROM minute_kline_cache WHERE ts_code=? AND freq="5min"', conn, params=[c])
    n = int(df.iloc[0]['n'])
    df1 = pd.read_sql('SELECT COUNT(*) AS n FROM minute_kline_cache WHERE ts_code=? AND freq="1min"', conn, params=[c])
    n1 = int(df1.iloc[0]['n'])
    print(f"  {c}: 5min={n} 行  1min={n1} 行  （5min==0 属真实缺失，非查错库）")

# b) 分库读 daily_cache 交易日
conn = sharding_manager.get_connection('market_cache.db')
tdf = pd.read_sql('SELECT DISTINCT trade_date FROM daily_cache ORDER BY trade_date DESC LIMIT 20', conn)
print(f"  daily_cache 最近交易日 {len(tdf)} 个: {tdf['trade_date'].iloc[0]} ... {tdf['trade_date'].iloc[-1]}")

# c) 总库确无 minute/daily 表（证明原直读总库必失败）
sc = sharding_manager.get_connection('stock_cache.db')
names = pd.read_sql("SELECT name FROM sqlite_master WHERE type='table' AND name IN ('minute_kline_cache','daily_cache')", sc)
print(f"  总库 stock_cache.db 命中 minute/daily 表数 = {len(names)}（0 = 原直读必失败，与 498#2 一致）")

print()
print("=== #3 三源 volume 归「手」验证 ===")
import urllib.request
# Sina: 字段8=股 → /100 = 手
url = 'https://hq.sinajs.cn/list=sh600519,sz000001'
req = urllib.request.Request(url, headers={'Referer': 'https://finance.sina.com.cn', 'User-Agent': 'Mozilla/5.0'})
raw = urllib.request.urlopen(req, timeout=8).read().decode('gbk')
for line in raw.strip().split('\n'):
    if not line.strip():
        continue
    head, _, tail = line.partition('="')
    sym = head.split('_')[-1]                 # 如 sh600519 / sz000001
    v = tail.rstrip('";').split(',')
    name = v[0]; price = float(v[3]); vol_share = float(v[8]); amt = float(v[9])
    hands_new = int(vol_share / 100)          # 修正后
    hands_old = int(vol_share * 100)          # 修正前
    ts = f"{sym[2:]}.SH" if sym.startswith('sh') else f"{sym[2:]}.SZ"
    # 与日线 vol（手）比对
    dconn = sharding_manager.get_connection('market_cache.db')
    d = pd.read_sql('SELECT trade_date, vol FROM daily_cache WHERE ts_code=? ORDER BY trade_date DESC LIMIT 1', dconn, params=[ts])
    dvol = float(d['vol'].iloc[0]) if len(d) else None
    print(f"  {name}({ts}): price={price} 新浪字段8(股)={vol_share:.0f}")
    print(f"    修正后 volume(手)={hands_new}  修正前={hands_old}(×100 错)  日线 vol(手)={dvol}（日线为全日，快照为盘中）")

print()
print("=== #12 请求预算解耦验证（纯逻辑）===")
MAX_PER_TICK = 50
_half = MAX_PER_TICK // 2
# 复现：积压时 fin/stk 预算吃满
_fin_done = _half  # finance 满额
_stk_done = _half  # stk_holder 满额
old_processed = _fin_done + _stk_done
new_processed = 0
pending_generic = ['full_daily', 'full_moneyflow', 'per_stock', 'adj_factor', 'concept']
def simulate(processed):
    done = 0
    for t in pending_generic:
        if processed >= MAX_PER_TICK:
            return done, 'STARVED'
        processed += 1
        done += 1
    return done, 'OK'
print(f"  旧 processed={old_processed} → 通用请求 {simulate(old_processed)}（0 done=全部饿死）")
print(f"  新 processed={new_processed} → 通用请求 {simulate(new_processed)}（全部推进）")
