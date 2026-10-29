"""数据源当日可采时点探针（552 配套，只读）。

目的：实测 2026-10-29 各数据源「当日数据首次可采」的时刻，为「按源就绪顺序启动」提供依据。
- Tushare: daily / daily_basic / moneyflow / stk_limit / top_list(lhb)
- 同花顺公开端点: line(日线) / time(分时) / realhead(实时快照)

约束：只读。不写库、不 import data_daemon、不 create_app、不起采集器。
输出：
- logs/source_probe_YYYYMMDD.jsonl   每轮一行 JSON
- logs/source_probe_YYYYMMDD.log     人读日志
- logs/source_probe_YYYYMMDD_summary.json  首达时刻汇总

用法：
    cd backend && .venv/bin/python3 -u scripts/_552_source_probe.py            # 等到 15:00 自动开跑
    cd backend && .venv/bin/python3 -u scripts/_552_source_probe.py --once     # 立即探测一轮（冒烟）
"""
import json
import os
import re
import sqlite3
import sys
import time
import urllib.request
from datetime import datetime, timedelta

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ROOT = os.path.dirname(BASE)
DATE = os.environ.get('PROBE_DATE', '2026-10-29')
DATE_COMPACT = DATE.replace('-', '')
LOG_DIR = os.path.join(ROOT, 'logs')
os.makedirs(LOG_DIR, exist_ok=True)
JSONL = os.path.join(LOG_DIR, f'source_probe_{DATE_COMPACT}.jsonl')
TXT = os.path.join(LOG_DIR, f'source_probe_{DATE_COMPACT}.log')
SUMMARY = os.path.join(LOG_DIR, f'source_probe_{DATE_COMPACT}_summary.json')

START_AT = datetime.strptime(f'{DATE} 15:00:00', '%Y-%m-%d %H:%M:%S')
END_AT = datetime.strptime(f'{DATE} 20:30:00', '%Y-%m-%d %H:%M:%S')
INTERVAL = 300
UA = ('Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) '
      'AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120 Safari/537.36')

CRITICAL = ('daily', 'daily_basic', 'moneyflow', 'stk_limit')


def log(msg: str):
    line = f"[{datetime.now():%H:%M:%S}] {msg}"
    print(line, flush=True)
    with open(TXT, 'a', encoding='utf-8') as f:
        f.write(line + '\n')


def _baseline_counts() -> dict:
    """读 10-28 行数作阈值基准（只读）。"""
    out = {}
    db = os.path.join(ROOT, 'data', 'duckdb', 'market_cache.db')
    try:
        con = sqlite3.connect(f'file:{db}?mode=ro', uri=True)
        for t in ('daily_cache', 'daily_basic_cache', 'moneyflow_cache', 'stk_limit_cache'):
            try:
                out[t] = con.execute(
                    "SELECT COUNT(*) FROM " + t + " WHERE trade_date=?", ['2026-10-28']).fetchone()[0]
            except Exception:
                out[t] = 0
        con.close()
    except Exception:
        pass
    return out


def _ts_pro_counts() -> dict:
    from dotenv import load_dotenv
    load_dotenv(os.path.join(ROOT, '.env'))
    import tushare as ts
    tok = os.environ.get('TUSHARE_TOKEN') or ''
    pro = ts.pro_api(tok) if tok else ts.pro_api()
    calls = {
        'daily': pro.daily,
        'daily_basic': pro.daily_basic,
        'moneyflow': pro.moneyflow,
        'stk_limit': pro.stk_limit,
        'lhb': pro.top_list,
    }
    out = {}
    for name, fn in calls.items():
        try:
            df = fn(trade_date=DATE_COMPACT)
            out[name] = 0 if df is None else len(df)
        except Exception as e:
            out[name] = -1
            out[name + '_err'] = f'{type(e).__name__}: {str(e)[:120]}'
    return out


def _ths_get(url: str) -> str:
    req = urllib.request.Request(url, headers={'User-Agent': UA,
                                               'Referer': 'https://stockpage.10jqka.com.cn/'})
    with urllib.request.urlopen(req, timeout=10) as r:
        return r.read().decode('utf-8', 'ignore')


def _ths_probe() -> dict:
    out = {}
    try:
        body = _ths_get('https://d.10jqka.com.cn/v6/line/hs_000001/01/last.js')
        m = re.search(r'\((\{.*\})\)', body, re.S)
        data = json.loads(m.group(1)).get('data') or '' if m else ''
        last = data.strip().split(';')[-1] if data.strip() else ''
        out['line_last_bar'] = last.split(',')[0] if last else None
        out['line_has_today'] = out['line_last_bar'] == DATE_COMPACT
    except Exception as e:
        out['line_last_bar'] = None
        out['line_has_today'] = False
        out['line_err'] = f'{type(e).__name__}: {str(e)[:100]}'
    try:
        body = _ths_get('https://d.10jqka.com.cn/v6/time/hs_000001/last.js')
        m = re.search(r'"date":"(\d{8})"', body)
        out['time_date'] = m.group(1) if m else None
        out['time_has_today'] = out['time_date'] == DATE_COMPACT
    except Exception as e:
        out['time_date'] = None
        out['time_has_today'] = False
        out['time_err'] = f'{type(e).__name__}: {str(e)[:100]}'
    try:
        body = _ths_get('https://d.10jqka.com.cn/v6/realhead/hs_000001/defer/last.js')
        out['realhead_ok'] = body.startswith('quotebridge_') and len(body) > 50
    except Exception:
        out['realhead_ok'] = False
    return out


def probe_round(baseline: dict) -> dict:
    now = datetime.now()
    rec = {'ts': now.strftime('%Y-%m-%d %H:%M:%S')}
    rec.update(_ts_pro_counts())
    rec.update(_ths_probe())
    # 就绪判定（阈值 = max(4000, 10-28 行数 × 95%)）
    for name, table in (('daily', 'daily_cache'), ('daily_basic', 'daily_basic_cache'),
                        ('moneyflow', 'moneyflow_cache'), ('stk_limit', 'stk_limit_cache')):
        need = max(4000, int(baseline.get(table, 0) * 0.95))
        rec[name + '_need'] = need
        rec[name + '_ready'] = rec.get(name, 0) >= need
    rec['lhb_ready'] = rec.get('lhb', 0) > 0
    with open(JSONL, 'a', encoding='utf-8') as f:
        f.write(json.dumps(rec, ensure_ascii=False) + '\n')
    return rec


def fmt(rec: dict) -> str:
    parts = [f"{k}={rec.get(k)}/{rec.get(k + '_need')}" for k in CRITICAL]
    return (f"{rec['ts']} | " + ' '.join(parts)
            + f" | lhb={rec.get('lhb')} | THS_line={rec.get('line_last_bar')}"
            f"(today={rec.get('line_has_today')}) THS_time={rec.get('time_date')}"
            f" realhead={rec.get('realhead_ok')}")


def main():
    once = '--once' in sys.argv
    baseline = _baseline_counts()
    log(f"探针启动 目标日={DATE} 基准行数={baseline} 起始={START_AT:%H:%M} 结束={END_AT:%H:%M}")
    if once:
        rec = probe_round(baseline)
        log(fmt(rec))
        return

    while datetime.now() < START_AT:
        time.sleep(30)
    first_ready = {}
    while datetime.now() <= END_AT:
        rec = probe_round(baseline)
        log(fmt(rec))
        for k in CRITICAL + ('lhb', 'line_has_today'):
            if k == 'line_has_today':
                if rec.get(k) and 'ths_line' not in first_ready:
                    first_ready['ths_line'] = rec['ts']
            elif rec.get(k + '_ready') and k not in first_ready:
                first_ready[k] = rec['ts']
        all_ready = all(rec.get(k + '_ready') for k in CRITICAL) and rec.get('line_has_today')
        if all_ready and len(first_ready) >= 5:
            log('关键四表 + 同花顺日线均已就绪，提前结束探测')
            break
        time.sleep(INTERVAL)

    out = {'date': DATE, 'baseline': baseline, 'first_ready': first_ready}
    with open(SUMMARY, 'w', encoding='utf-8') as f:
        json.dump(out, f, ensure_ascii=False, indent=2)
    log(f"探测结束 首达时刻={json.dumps(first_ready, ensure_ascii=False)}")


if __name__ == '__main__':
    main()
