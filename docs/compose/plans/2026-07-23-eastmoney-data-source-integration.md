# East Money HTTP API 替代 mootdx 实时行情实施方案

> **For agentic workers:** REQUIRED SUB-SKILL: Use compose:subagent to implement task-by-task.

**Goal:** Replace broken mootdx TCP `quotes()` with East Money HTTP API as primary real-time market data source

**Architecture:** Add `_fetch_eastmoney()` function, update `_SnapshotSourceManager` to prioritize East Money, fix `MootdxCollector.start()` to run without mootdx

**Tech Stack:** Python, urllib, concurrent.futures

---

### Task 1: Add East Money HTTP API fetcher

**Files:**
- Modify: `backend/app/data/mootdx_collector.py` (add `_fetch_eastmoney()` function after `_fetch_tencent`)

- [ ] **Step 1: Add `_fetch_eastmoney()` function**

```python
# ── East Money 解析器（289号方案：主源替代 mootdx） ─────────

def _fetch_eastmoney(codes: list, name_map: dict) -> list:
    """从 push2.eastmoney.com 获取实时行情（主源）

    使用 ulist.np 批量端点，fltt=2 自动缩放，60只/批，
    并行4线程采集，全市场5000只约5s。

    东财字段 → 内部字段映射:
      f2=price, f3=change_pct, f4=change, f5=volume(手),
      f6=amount, f7=amplitude, f12=6位代码, f14=name,
      f15=high, f16=low, f17=open, f18=prev_close,
      f20=总市值, f21=流通市值, f57=完整ts_code, f60=昨收原始值
    """
    import urllib.request
    import json
    import concurrent.futures

    all_records = []
    batch_size = 60
    max_workers = 4
    field_str = 'f2,f3,f4,f5,f6,f7,f8,f10,f12,f14,f15,f16,f17,f18,f20,f21,f57,f60'

    def _fetch_batch(code_batch: list) -> list:
        """单批获取并解析"""
        secids = ','.join(
            f"1.{c}" if c.startswith(('6', '9')) else f"0.{c}"
            for c in code_batch
        )
        url = (f"https://push2.eastmoney.com/api/qt/ulist.np/get"
               f"?fltt=2&fields={field_str}&secids={secids}")
        req = urllib.request.Request(url, headers={
            'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7)',
            'Referer': 'https://www.eastmoney.com/',
        })
        try:
            with urllib.request.urlopen(req, timeout=10) as resp:
                raw = resp.read().decode('utf-8')
                data = json.loads(raw)
                diff = data.get('data', {}).get('diff', [])
        except Exception:
            return []

        records = []
        for s in diff:
            if not s or not s.get('f12'):
                continue
            code = str(s.get('f12', ''))
            price = _safe_float(s.get('f2'))
            prev_close = _safe_float(s.get('f18'))
            if price == 0 or prev_close == 0:
                continue

            change = round(price - prev_close, 2)
            change_pct = round(change / prev_close * 100, 2) if prev_close else 0.0
            market = 0 if code.startswith(('6', '9')) else 1
            ts_code = f'{code}.SH' if market == 0 else f'{code}.SZ'

            records.append({
                'ts_code': ts_code,
                'code': code,
                'name': s.get('f14', '') or name_map.get(code, ''),
                'price': price,
                'change': change,
                'change_pct': change_pct,
                'open': _safe_float(s.get('f17')),
                'high': _safe_float(s.get('f15')),
                'low': _safe_float(s.get('f16')),
                'prev_close': prev_close,
                'volume': int(_safe_float(s.get('f5', 0))),
                'amount': _safe_float(s.get('f6')),
                'bid1': 0.0, 'ask1': 0.0,
                'bid_vol1': 0, 'ask_vol1': 0,
                'bid2': 0.0, 'ask2': 0.0,
                'bid_vol2': 0, 'ask_vol2': 0,
                'bid3': 0.0, 'ask3': 0.0,
                'bid_vol3': 0, 'ask_vol3': 0,
                'bid4': 0.0, 'ask4': 0.0,
                'bid_vol4': 0, 'ask_vol4': 0,
                'bid5': 0.0, 'ask5': 0.0,
                'bid_vol5': 0, 'ask_vol5': 0,
                'commission': 0.0,
                'speed': _calc_speed(code, price),
                'timestamp': datetime.now().isoformat(),
                'source': 'eastmoney',
            })
        return records

    # 分批并行采集
    batches = [codes[i:i + batch_size] for i in range(0, len(codes), batch_size)]
    with concurrent.futures.ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = [executor.submit(_fetch_batch, b) for b in batches]
        for f in concurrent.futures.as_completed(futures):
            try:
                result = f.result()
                if result:
                    all_records.extend(result)
            except Exception:
                continue

    return all_records
```

- [ ] **Step 2: Update `_SourceSnapshotManager._fetch_source()` to handle 'eastmoney'**

Edit the `_fetch_source` method to add the eastmoney case:

```python
    def _fetch_source(self, source: str, codes: list, name_map: dict) -> list:
        if source == 'eastmoney':
            return _fetch_eastmoney(codes, name_map)
        if source == 'sina':
            return _fetch_sina(codes, name_map)
        return _fetch_tencent(codes, name_map)
```

- [ ] **Step 3: Change default primary source to 'eastmoney'**

In `_SnapshotSourceManager.__init__`, change `self._primary` from `'sina'` to `'eastmoney'`:

```python
    def __init__(self):
        self._primary = 'eastmoney'  # 东财主源，Sina/Tencent 备源
        self._consecutive_failures = 0
        self._recovery_successes = 0
```

### Task 2: Fix collector startup to work without mootdx

**Files:**
- Modify: `backend/app/data/mootdx_collector.py` (MootdxCollector.start, collect_market_snapshot)

- [ ] **Step 1: Modify `MootdxCollector.start()` to start snapshot thread without mootdx**

The snapshot thread should run regardless of mootdx availability. Only the minute thread needs mootdx.

Change lines 1243-1260. Current code:

```python
        client = _get_client()
        if client is None:
            logger.warning("mootdx 不可用，MootdxCollector 未启动")
            return False
```

Replace with:

```python
        # mootdx 不再作为快照采集的必需条件（289号：通达信协议断裂，改用东财HTTP）
        # 分钟数据仍尝试使用 mootdx（minutes() 尚可用）
        client = _get_client()
        if client is None:
            logger.info("mootdx 客户端不可用，快照使用 HTTP 降级（东财/新浪/腾讯）")
```

Also, the minute_full thread should only start if mootdx is available:

Change the thread list construction. Replace:

```python
        self._threads = [
            _MootdxThread('market_snapshot', 5, collect_market_snapshot, initial_delay=3),
            _MootdxThread('minute_full', 300, collect_minute_full, initial_delay=60,
                          check_trading_time=False),
        ]
```

With:

```python
        self._threads = [
            _MootdxThread('market_snapshot', 5, collect_market_snapshot, initial_delay=3),
        ]
        # 分钟数据仍需 mootdx minutes()（该API尚可用）
        if client is not None:
            self._threads.append(
                _MootdxThread('minute_full', 300, collect_minute_full, initial_delay=60,
                              check_trading_time=False),
            )
```

- [ ] **Step 2: Modify `collect_market_snapshot()` to go straight to HTTP when mootdx unavailable**

Change the early return at lines 296-298. Replace:

```python
    client = _get_client()
    if client is None:
        logger.warning("[mootdx] 客户端不可用，跳过快照采集")
        return 0
```

With:

```python
    client = _get_client()
    if client is None:
        # mootdx 不可用，直接使用 HTTP 降级（289号方案：东财主源 → 新浪 → 腾讯）
        return _collect_dual_source_fallback()
```

### Task 3: Update data_daemon startup logging

**Files:**
- Modify: `backend/data_daemon.py`

- [ ] **Step 1: Update startup logging to reflect East Money being primary source**

In `_start_collectors()`, modify the mootdx startup logging:

```python
        from app.data.mootdx_collector import mootdx_collector
        if mootdx_collector.start():
            ok.append('mootdx')
            logger.info("MootdxCollector 已启动（快照:东财HTTP, 分钟:mootdx）")
        else:
            logger.warning("MootdxCollector 启动失败（mootdx TCP 不可用）")
```

### Task 4: Verify

- [ ] **Step 1: Run data_daemon to verify**

```bash
cd backend && python data_daemon.py
```

Check that:
- MootdxCollector starts (even without mootdx quotes)
- Market snapshot uses East Money HTTP
- Log shows `[eastmoney] 实时行情降级完成`
- Data is written to InMemoryStateStore

- [ ] **Step 2: Verify key fields are correct**

Check that East Money HTTP returns:
- Correct price values (fltt=2 scaling)
- volume/amount fields
- Stock names resolve correctly

- [ ] **Step 3: Verify start.command compatibility**

`start.command` already sets `DATA_DAEMON_RUNNING=1` for the API process. The data_daemon launchd plist is unchanged since the daemon auto-starts.
