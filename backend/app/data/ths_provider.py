"""553-C：同花顺公开端点兜底（time 分时 / realhead 单只快照）。

只接 `time` 与 `realhead`，**不接 `line`**——10-29 实测 20:28 同花顺日线仍未出现当日 bar，
比 Tushare（15:50 可采）晚 4.5 小时以上，不适合做 daily 提前源。

约束：
- 本模块只做 HTTP 读取与解析，不写库；分钟兜底由采集层（data_daemon）调用并落 ECM。
- `realhead` 是**逐只**请求，仅用于单只/交互兜底，禁止用于全市场 5s 轮询。
"""
import json
import re
import urllib.request

import pandas as pd

_UA = ('Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) '
       'AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120 Safari/537.36')
_REFERER = 'https://stockpage.10jqka.com.cn/'
_BASE = 'https://d.10jqka.com.cn/v6'


def _code(ts_code: str) -> str:
    return str(ts_code).split('.')[0]


def _get(url: str, timeout: int = 8) -> str:
    req = urllib.request.Request(url, headers={'User-Agent': _UA, 'Referer': _REFERER})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return resp.read().decode('utf-8', 'ignore')


def _load_jsonp(body: str) -> dict:
    m = re.search(r'\((\{.*\})\)\s*;?\s*$', body, re.S)
    if not m:
        return {}
    return json.loads(m.group(1))


def fetch_intraday_minutes(ts_code: str, date_str: str, timeout: int = 8) -> pd.DataFrame:
    """同花顺分时（1 分钟）→ minute_kline_cache 结构。

    `time` 端点字段：`HHMM,price,amount,avg_price,volume`（逐分钟）。
    分时只有每分钟一个价格，故 open=high=low=close=price。
    返回列：trade_date / trade_time / open / high / low / close / volume / amount；
    日期不匹配或解析失败返回空 DataFrame。
    """
    code = _code(ts_code)
    want = str(date_str).replace('-', '')
    try:
        body = _get(f'{_BASE}/time/hs_{code}/last.js', timeout)
    except Exception:
        return pd.DataFrame()
    payload = _load_jsonp(body)
    node = payload.get(f'hs_{code}') or (next(iter(payload.values())) if payload else {})
    if not isinstance(node, dict):
        return pd.DataFrame()
    got = str(node.get('date') or '')
    if got != want:
        return pd.DataFrame()
    day = f'{got[:4]}-{got[4:6]}-{got[6:8]}'
    rows = []
    for seg in str(node.get('data') or '').split(';'):
        parts = seg.split(',')
        if len(parts) < 5:
            continue
        hhmm, price, amount, _avg, volume = parts[:5]
        try:
            rows.append({
                'trade_date': day,
                'trade_time': f'{day} {hhmm[:2]}:{hhmm[2:]}:00',
                'open': float(price), 'high': float(price),
                'low': float(price), 'close': float(price),
                'volume': float(volume), 'amount': float(amount),
            })
        except (TypeError, ValueError):
            continue
    return pd.DataFrame(rows)


def fetch_snapshot_raw(ts_code: str, timeout: int = 8) -> dict:
    """同花顺单只实时快照（realhead）原始 items。

    该端点字段是数字键（如 "10"/"8"/"9"/"7"），语义随页面版本变化，
    这里只返回原始 dict 供调用方按需映射；**不要**在全市场轮询中逐只调用。
    """
    code = _code(ts_code)
    try:
        payload = _load_jsonp(_get(f'{_BASE}/realhead/hs_{code}/defer/last.js', timeout))
    except Exception:
        return {}
    items = payload.get('items')
    return items if isinstance(items, dict) else {}
