"""520号 定向测试：QA-CHECK margin_cache 最新交易日豁免（T+1 发布窗口）。

背景：margin（融资融券明细）源侧次一交易日才发布（Tushare margin_detail 对 T 日
数据次日/跨周末才回）——QA-CHECK 在最新交易日（刚完成 EOD 的日期）校验 margin 覆盖
判定必假失败（10-09 45%、10-13 0% 实证，且无补算映射 → 重试超限告警）。
处置（拍板 A）：QUALITY_RULES['margin_cache'] 加 skip_latest_day——pipeline_date
为 daily_cache 最新交易日时跳过覆盖判定；历史日期照常校验。
"""
from app.data.stg_quality import QUALITY_RULES, QualityChecker


def test_margin_rule_has_skip_latest_day_flag():
    """margin_cache 规则应带 skip_latest_day 标志（520号）"""
    assert QUALITY_RULES['margin_cache'].get('skip_latest_day') is True


def test_margin_latest_day_exempt(monkeypatch):
    """最新交易日：即使当日 0 行也通过（覆盖判定被跳过）"""
    checker = QualityChecker()
    monkeypatch.setattr(checker, '_latest_daily_date', lambda: '2026-10-13')
    monkeypatch.setattr(checker, '_count_by_date', lambda t, d: 0)
    r = checker.check_table('margin_cache', '2026-10-13')
    assert r.passed, f"最新交易日 margin 应豁免覆盖判定: {r.issues}"


def test_margin_historical_day_still_checked(monkeypatch):
    """历史日期（非最新交易日）：照常覆盖判定，0 行 → 失败"""
    checker = QualityChecker()
    monkeypatch.setattr(checker, '_latest_daily_date', lambda: '2026-10-13')
    monkeypatch.setattr(checker, '_baseline_rows', lambda t, d, days=20: 4455)
    monkeypatch.setattr(checker, '_count_by_date', lambda t, d: 0)
    r = checker.check_table('margin_cache', '2026-10-12')
    assert not r.passed
    assert any('覆盖率不足' in i for i in r.issues)


def test_other_table_not_exempted(monkeypatch):
    """非 skip_latest_day 表（status_snapshot）：最新交易日也照常覆盖判定"""
    checker = QualityChecker()
    monkeypatch.setattr(checker, '_latest_daily_date', lambda: '2026-10-13')
    monkeypatch.setattr(checker, 'daily_base', lambda d: 5000)
    monkeypatch.setattr(checker, '_count_by_date', lambda t, d: 1000)
    r = checker.check_table('status_snapshot', '2026-10-13')
    assert not r.passed
    assert any('覆盖率不足' in i for i in r.issues)


class _FakeMaxConn:
    """记录 SQL，返回固定 MAX 值（不碰真实库）"""
    def __init__(self, latest):
        self.latest = latest

    def execute(self, sql):
        class _R:
            def __init__(self, v):
                self._v = v

            def fetchone(self):
                return (self._v,)
        return _R(self.latest)


class _FakeMaxSM:
    def __init__(self, conn):
        self._conn = conn

    def get_db_for_table(self, table):
        return 'market_cache.db'

    def get_connection(self, db):
        return self._conn


def test_latest_daily_date_queries_daily_cache(monkeypatch):
    """_latest_daily_date 应读 daily_cache 最新交易日（'YYYY-MM-DD'）"""
    checker = QualityChecker()
    conn = _FakeMaxConn('2026-10-13')
    monkeypatch.setattr(checker, '_sm', _FakeMaxSM(conn))
    assert checker._latest_daily_date() == '2026-10-13'


def test_latest_daily_date_empty_returns_empty(monkeypatch):
    """daily_cache 无数据 → 返回 ''（不误判为最新交易日）"""
    checker = QualityChecker()
    conn = _FakeMaxConn(None)
    monkeypatch.setattr(checker, '_sm', _FakeMaxSM(conn))
    assert checker._latest_daily_date() == ''
