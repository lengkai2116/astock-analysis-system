"""521号 O2/O3 — 完整性检查财务表时效列名修复 + news 采集换源

O2：`_check_data_timeliness` 背景表（4 张财务表）原查 `MAX(trade_date)`，
但财务表列是 `end_date/ann_date`（无 trade_date）→ 恒 `no such column`
→ 4 项时效检查形同虚设；修复为按公告日 `MAX(ann_date)` 判定。
O3：`akshare_collector._collect_lhb_and_news` 新闻段原调 `ak.stock_news_em()`
（akshare 库内 `r"\\u3000"` 正则与 pyarrow 20 不兼容 → 必现失败）；
换用 `ak.stock_info_global_em()`（全市场财经快讯，列=标题/摘要/发布时间/链接）。
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
for k in ['HTTP_PROXY', 'HTTPS_PROXY', 'ALL_PROXY', 'http_proxy', 'https_proxy', 'all_proxy']:
    os.environ.pop(k, None)


# ── O2：背景财务表时效检查用 ann_date ─────────────────────

def test_timeliness_background_tables_use_ann_date(monkeypatch):
    """4 张财务表时效检查应查 MAX(ann_date)，不得再查 MAX(trade_date)"""
    import data_daemon

    captured = {}  # table -> sql

    def fake_query_table(table, sql, params=None):
        captured[table] = sql
        return None  # latest falsy → 不触发日期解析分支

    monkeypatch.setattr(data_daemon, '_query_table', fake_query_table)
    monkeypatch.setattr(data_daemon, '_get_adj_latest_date', lambda: None)
    monkeypatch.setattr(data_daemon, '_lag_trading_days', lambda a, b: 0)

    data_daemon._check_data_timeliness()

    bg = ['fina_indicator_cache', 'income_cache', 'balancesheet_cache', 'cashflow_cache']
    for t in bg:
        sql = captured.get(t, '')
        assert 'MAX(ann_date)' in sql, f"{t} 应查 MAX(ann_date)，实得: {sql}"
        assert 'trade_date' not in sql, f"{t} 不应再查 trade_date，实得: {sql}"


# ── O3：news 采集换用 stock_info_global_em 并正确映射 ──────

def test_news_collector_uses_global_em_and_maps(monkeypatch):
    """新闻段应调 stock_info_global_em，并把 标题/摘要/发布时间/链接 映射进 records"""
    import pandas as pd

    import app.data.akshare_collector as ac
    from app.data import in_memory_store

    fake_df = pd.DataFrame([
        {'标题': '快讯A', '摘要': '摘要A', '发布时间': '2026-10-15 12:00:00', '链接': 'https://eastmoney.com/a'},
        {'标题': '快讯B', '摘要': '摘要B', '发布时间': '2026-10-15 12:01:00', '链接': 'https://eastmoney.com/b'},
    ])

    class FakeAk:
        def stock_lhb_detail_em(self, start_date='', end_date=''):
            return None  # 龙虎榜段跳过
        def stock_info_global_em(self):
            return fake_df

    monkeypatch.setattr(ac, '_get_ak', lambda: FakeAk())
    monkeypatch.setattr(ac, '_get_ecm', lambda: object())  # 龙虎榜段不触发即不用

    store = in_memory_store.get_instance() if hasattr(in_memory_store, 'get_instance') else None
    # 直接调采集函数（其内部调 mem_store.update_news）
    ac._collect_lhb_and_news()

    # 通过模块级 mem_store 读回验证
    news = ac.mem_store.get_news() if hasattr(ac, 'mem_store') else None
    if news is None:
        # 回退：读 in_memory_store 模块级单例
        news = in_memory_store._mem_store.get_news() if hasattr(in_memory_store, '_mem_store') else None
    assert news is not None and len(news) == 2, f"应写入 2 条新闻，实得: {news}"
    first = news[0]
    assert first['title'] == '快讯A', f"title 映射错: {first}"
    assert first['content'] == '摘要A', f"content 映射错: {first}"
    assert first['publish_time'] == '2026-10-15 12:00:00', f"publish_time 映射错: {first}"
    assert first['source'] == 'https://eastmoney.com/a', f"source（链接）映射错: {first}"
    assert first['ts_code'] == '', f"全市场快讯 ts_code 应为空串: {first}"
