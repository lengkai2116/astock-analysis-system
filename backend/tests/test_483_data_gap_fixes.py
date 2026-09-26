"""483号：数据缺口核查与处置（口径层 A1 + 采集层 ③②）回归测试

覆盖：
- app.data.market_universe：个股宇宙 SSOT（is_index_code / stock_only_sql）
- QualityChecker：daily_base 剔指数（个股宇宙基准）+ margin 自基准（③b）
- dim1 契约：lhb_df 稀疏容忍（①）
- minute_backfill：1min→60min 本地聚合 + trade_date 补齐（②）
"""
import pandas as pd

from app.data.market_universe import is_index_code, stock_only_sql


class TestMarketUniverse:
    def test_broad_index_codes(self):
        for c in ['000001.SH', '000300.SH', '399001.SZ', '399006.SZ', '899050.BJ']:
            assert is_index_code(c), c

    def test_sw_index_and_suffix(self):
        for c in ['801010.SI', '801780.SI', '999999.SI']:
            assert is_index_code(c), c

    def test_399_segment(self):
        assert is_index_code('399001.SZ')
        assert is_index_code('399999.SZ')

    def test_real_stocks_not_index(self):
        # 000001.SZ 是平安银行（与 000001.SH 上证指数同号不同所）
        for c in ['000001.SZ', '600519.SH', '300750.SZ', '002594.SZ',
                  '600036.SH', '920020.BJ', '688981.SH']:
            assert not is_index_code(c), c

    def test_empty(self):
        assert not is_index_code('')
        assert not is_index_code(None)

    def test_stock_only_sql(self):
        sql, params = stock_only_sql()
        assert "NOT LIKE '%.SI'" in sql and "NOT LIKE '399%'" in sql
        assert sql.count('?') == len(params)
        assert '000001.SH' in params and '801010.SI' in params
        # 别名版本
        sql_a, _ = stock_only_sql('d')
        assert 'd.ts_code' in sql_a


class _FakeCursor:
    def __init__(self, val):
        self._val = val

    def fetchone(self):
        return (self._val,)


class _FakeConn:
    def __init__(self, val, sink):
        self._val = val
        self._sink = sink

    def execute(self, sql, params=None):
        self._sink.append((sql, params))
        return _FakeCursor(self._val)


class _FakeSM:
    def __init__(self, val, sink):
        self._val = val
        self._sink = sink

    def get_db_for_table(self, table):
        return 'market_cache.db'

    def get_connection(self, db):
        return _FakeConn(self._val, self._sink)


def _checker(val=5510):
    """构造不触发真实分库初始化的 QualityChecker（只需 _sm）。"""
    from app.data.stg_quality import QualityChecker
    c = QualityChecker.__new__(QualityChecker)
    c._ecm = None
    sink = []
    c._sm = _FakeSM(val, sink)
    return c, sink


class TestQaDailyBase:
    def test_daily_base_excludes_index(self):
        """daily_base 的 SQL 必须带「仅个股」谓词（483 ④）"""
        c, sink = _checker(val=5510)
        assert c.daily_base('2026-09-24') == 5510
        sql, params = sink[-1]
        assert 'daily_cache' in sql and "NOT LIKE '%.SI'" in sql and "NOT LIKE '399%'" in sql
        assert '2026-09-24' in params

    def test_indicator_ma_passes_with_stock_base(self, monkeypatch):
        """④：个股基准下 indicator_ma 5510/5510 通过（原 5510/5536 假失败）"""
        c, _ = _checker()
        monkeypatch.setattr(c, 'daily_base', lambda d: 5510)
        monkeypatch.setattr(c, '_count_by_date', lambda t, d: 5510)
        monkeypatch.setattr(c, '_count_null_fields', lambda t, d, req: 0)
        r = c.check_table('indicator_ma', '2026-09-24')
        assert r.passed


class TestMarginSelfBaseline:
    def test_partial_day_flagged(self, monkeypatch):
        """③：09-24 部分入库 2002/自基准4451 → 检出覆盖率不足"""
        c, _ = _checker()
        monkeypatch.setattr(c, '_baseline_rows', lambda t, d: 4451)
        monkeypatch.setattr(c, '_count_by_date', lambda t, d: 2002)
        r = c.check_table('margin_cache', '2026-09-24')
        assert not r.passed
        assert any('覆盖率不足' in i for i in r.issues)

    def test_normal_day_passes(self, monkeypatch):
        """③：常态 4400/4451(98.9%) → 通过"""
        c, _ = _checker()
        monkeypatch.setattr(c, '_baseline_rows', lambda t, d: 4451)
        monkeypatch.setattr(c, '_count_by_date', lambda t, d: 4400)
        assert c.check_table('margin_cache', '2026-09-23').passed

    def test_no_history_no_false_alarm(self, monkeypatch):
        """③：无历史基准可用时不误报"""
        c, _ = _checker()
        monkeypatch.setattr(c, '_baseline_rows', lambda t, d: 0)
        monkeypatch.setattr(c, '_count_by_date', lambda t, d: 100)
        r = c.check_table('margin_cache', '2026-09-24')
        assert r.passed

    def test_daily_base_not_used_for_margin(self, monkeypatch):
        """③b：margin 走自基准，不再用 daily_cache 锚（否则 0.95×5592=5312 恒失败）"""
        c, _ = _checker()
        monkeypatch.setattr(c, 'daily_base', lambda d: (_ for _ in ()).throw(AssertionError('不应调用 daily_base')))
        monkeypatch.setattr(c, '_baseline_rows', lambda t, d: 4451)
        monkeypatch.setattr(c, '_count_by_date', lambda t, d: 4400)
        assert c.check_table('margin_cache', '2026-09-23').passed


class TestDim1LhbSparse:
    def _ctx(self):
        return {
            'daily_df': pd.DataFrame({'trade_date': ['20260101'], 'close': [10.0]}),
            'moneyflow_df': pd.DataFrame({'trade_date': ['20260101']}),
        }

    def test_lhb_not_in_missing_contract(self):
        """①：无 lhb_df 不再计入 missing（稀疏事件表）"""
        from app.opportunity_atlas.dimensions.dim1_signal_engine import Dim1SignalEngine
        r = Dim1SignalEngine()._validate(self._ctx(), '000001.SZ')
        assert 'lhb_df' not in r['missing_tables']

    def test_lhb_loaded_still_in_context(self):
        """①：有 lhb_df 时仍注入 data_context（供 dim4/dim6 消费）"""
        from app.opportunity_atlas.dimensions.dim1_signal_engine import Dim1SignalEngine
        ctx = self._ctx()
        ctx['lhb_df'] = pd.DataFrame({'ts_code': ['000001.SZ'], 'net_amount': [1e4]})
        r = Dim1SignalEngine()._validate(ctx, '000001.SZ')
        assert 'lhb_df' not in r['missing_tables']


def _mk_1min_day(ts_code='000001.SZ', day='2026-09-24'):
    """构造一个交易日的 1min 记录（上午 120 + 下午 120 根）"""
    rows = []
    for start_h, mins in ((9, 30), (13, 0)):
        for i in range(120):
            m = start_h * 60 + mins + i
            hh, mm = divmod(m, 60)
            tt = f'{day} {hh:02d}:{mm:02d}:00'
            rows.append({
                'ts_code': ts_code, 'trade_date': day, 'trade_time': tt, 'freq': '1min',
                'open': 10.0, 'high': 10.2, 'low': 9.9, 'close': 10.1,
                'volume': 100.0, 'amount': 1000.0,
            })
    return pd.DataFrame(rows)


class _FakeECM:
    def __init__(self, df_1min):
        self._df = df_1min
        self.written = None

    def get_cached_minute_kline(self, ts_code, trade_date=None, freq='5min'):
        return self._df if freq == '1min' else pd.DataFrame()

    def cache_minute_kline(self, df):
        self.written = df


class TestMinuteAggregate60min:
    def test_resample_to_4_bars(self):
        """②：1min→60min 得每日 4 根（上午2+下午2）"""
        from app.data.minute_backfill import _resample_minute
        agg = _resample_minute(_mk_1min_day().to_dict('records'), '1min', '60min')
        assert len(agg) == 4

    def test_aggregate_writes_60min_with_trade_date(self):
        """②：聚合落库 freq=60min 且补齐 trade_date（PK 含 trade_date）"""
        from app.data.minute_backfill import aggregate_1min_to_60min
        ecm = _FakeECM(_mk_1min_day())
        n = aggregate_1min_to_60min(['000001.SZ'], ecm=ecm)
        assert n == 1
        w = ecm.written
        assert w is not None
        assert set(w['freq']) == {'60min'}
        assert set(w['trade_date']) == {'2026-09-24'}
        assert len(w) == 4

    def test_aggregate_skips_no_1min(self):
        """②：无 1min 的股票跳过（不写空）"""
        from app.data.minute_backfill import aggregate_1min_to_60min
        ecm = _FakeECM(pd.DataFrame())
        assert aggregate_1min_to_60min(['000001.SZ'], ecm=ecm) == 0
        assert ecm.written is None


class TestMarginCompletenessGate:
    """③ 后续：交易日闸门 + 发布机制感知（排除最新交易日）+ 日历不可用回退"""

    def test_recent_trading_days_skips_holidays(self):
        """交易日历：中秋 9/25-27 与周末剔除（含 09-20，483 校正后非交易日）"""
        import data_daemon as dd
        from datetime import datetime as _dt
        days = dd._recent_trading_days(6, end=_dt(2026, 9, 28))
        assert days == ['2026-09-18', '2026-09-21', '2026-09-22',
                        '2026-09-23', '2026-09-24', '2026-09-28']

    def test_margin_is_short(self):
        import data_daemon as dd
        assert dd._margin_is_short(2002, 4451) is True      # 45% → 不足
        assert dd._margin_is_short(4451, 4451) is False
        assert dd._margin_is_short(4005, 4451) is False     # 恰在 90% 线上
        assert dd._margin_is_short(100, 0) is False         # 无基准不判

    def test_gate_skips_non_trading_day(self, monkeypatch):
        """非交易日（如假期）→ 跳过且不触发任何回补"""
        import data_daemon as dd
        monkeypatch.setattr(dd, '_is_trading_day', lambda d: False)
        monkeypatch.setattr(dd, '_margin_rows_on',
                            lambda d: (_ for _ in ()).throw(AssertionError('不应查库')))
        monkeypatch.setattr(dd, '_batch_margin',
                            lambda d: (_ for _ in ()).throw(AssertionError('不应回补')))
        assert dd._check_margin_completeness() == []

    def test_window_excludes_latest_and_backfills_short_day(self, monkeypatch):
        """交易日：排除最新交易日；仅回补不足的历史日（09-24）"""
        import data_daemon as dd
        calls = []
        rows = {'2026-09-21': 4451, '2026-09-22': 4451,
                '2026-09-23': 4451, '2026-09-24': 2002, '2026-09-28': 2002}
        monkeypatch.setattr(dd, '_is_trading_day', lambda d: True)
        monkeypatch.setattr(dd, '_recent_trading_days',
                            lambda n, end=None: ['2026-09-21', '2026-09-22', '2026-09-23',
                                                 '2026-09-24', '2026-09-28'])
        monkeypatch.setattr(dd, '_shard_fetchall',
                            lambda t, sql, params=None: [(d,) for d in rows])
        monkeypatch.setattr(dd, '_margin_rows_on', lambda d: rows[d])
        monkeypatch.setattr(dd, '_margin_base_before', lambda d: 4451)
        monkeypatch.setattr(dd, '_batch_margin', lambda d: calls.append(d) or 2002)
        fixed = dd._check_margin_completeness(window=4)
        assert fixed == ['2026-09-24']
        assert calls == ['20260924']          # 最新日 09-28 未被核对（发布窗口内）

    def test_calendar_false_positive_filtered_by_market_data(self, monkeypatch):
        """日历误标休市日（无行情）→ 被数据侧过滤，不回补"""
        import data_daemon as dd
        calls = []
        monkeypatch.setattr(dd, '_is_trading_day', lambda d: True)
        # 日历把 2026-09-20（实际休市）也列为交易日
        monkeypatch.setattr(dd, '_recent_trading_days',
                            lambda n, end=None: ['2026-09-20', '2026-09-21', '2026-09-23',
                                                 '2026-09-24', '2026-09-28'])
        # daily_cache 无 09-20、无 09-28（尚未采集）
        monkeypatch.setattr(dd, '_shard_fetchall',
                            lambda t, sql, params=None: [('2026-09-24',), ('2026-09-23',),
                                                         ('2026-09-21',)])
        monkeypatch.setattr(dd, '_margin_rows_on', lambda d: 4451)
        monkeypatch.setattr(dd, '_margin_base_before', lambda d: 4451)
        monkeypatch.setattr(dd, '_batch_margin', lambda d: calls.append(d) or 0)
        fixed = dd._check_margin_completeness(window=4)
        assert fixed == [] and calls == []    # 09-20 被过滤，09-23/24 完整

    def test_simulated_post_holiday_checks_prev_trading_day(self, monkeypatch):
        """模拟节后首日 2026-09-28：应复查 09-24（其发布窗口已过），当日仍排除"""
        import data_daemon as dd
        from datetime import datetime as _dt

        class _FakeDT(_dt):
            @classmethod
            def now(cls, tz=None):
                return _dt(2026, 9, 28, 10, 0)

        calls = []
        monkeypatch.setattr(dd, 'datetime', _FakeDT)
        monkeypatch.setattr(dd, '_recent_trading_days',
                            lambda n, end=None: ['2026-09-20', '2026-09-21', '2026-09-22',
                                                 '2026-09-23', '2026-09-24', '2026-09-28'])
        monkeypatch.setattr(dd, '_shard_fetchall',
                            lambda t, sql, params=None: [('2026-09-24',), ('2026-09-23',),
                                                         ('2026-09-22',), ('2026-09-21',)])
        monkeypatch.setattr(dd, '_margin_rows_on',
                            lambda d: 2002 if d == '2026-09-24' else 4451)
        monkeypatch.setattr(dd, '_margin_base_before', lambda d: 4451)
        monkeypatch.setattr(dd, '_batch_margin', lambda d: calls.append(d) or 4451)
        fixed = dd._check_margin_completeness()
        assert fixed == ['2026-09-24']
        assert calls == ['20260924']      # 09-20（无行情）被过滤；09-28（当日）被排除

    def test_calendar_unavailable_falls_back_to_db(self, monkeypatch):
        """日历不可用 → 回退 DB 推导日期，仍执行核对（不静默跳过）"""
        import data_daemon as dd
        calls = []
        monkeypatch.setattr(dd, '_is_trading_day', lambda d: True)
        monkeypatch.setattr(dd, '_recent_trading_days', lambda n, end=None: [])
        monkeypatch.setattr(dd, '_shard_fetchall',
                            lambda t, sql, params=None: [('2026-09-24',), ('2026-09-23',),
                                                         ('2026-09-22',)])
        monkeypatch.setattr(dd, '_margin_rows_on',
                            lambda d: 2002 if d == '2026-09-22' else 4451)
        monkeypatch.setattr(dd, '_margin_base_before', lambda d: 4451)
        monkeypatch.setattr(dd, '_batch_margin', lambda d: calls.append(d) or 2002)
        fixed = dd._check_margin_completeness(window=2)
        assert fixed == ['2026-09-22'] and calls == ['20260922']
