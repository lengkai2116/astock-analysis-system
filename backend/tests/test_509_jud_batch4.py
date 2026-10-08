"""509号批次4：接口/写路径/单例验证（#J32~#J42）

方案档：`002-方案存档/509-JUD板块OCR核查与处置.md` §9.6。

批次4 实施范围（2026-10-08，Q5 已拍板=严格月份边界 + 6% 未舍入比较）：
  - #J34 opportunity_library update 先校验后 setattr（lib_level 域校验前置，非法值不入 ORM）；
  - #J35 opportunity_library 白名单字段类型/None 校验（数值列强制 cast、拒 null）；
  - #J36 opportunity_library 写端点 commit 包 try/except+rollback（防 PendingRollbackError 级联）；
  - #J37 opportunity_library search 转义 %/_ + 分页（page_size 硬上限 100）；
  - #J38 watchlist mf_sorted 无条件先初始化（单行+circ_mv>0 时原 NameError 吞掉资金流）；
  - #J39 watchlist _get_cache() 改模块级单例（原每次新建→报价缓存永不生效）；
  - #J40 opportunity_atlas 惰性单例加 threading.Lock 双检锁；
  - #J41 strategy_analyze deep_chip 统一仅存 float（无法数值化不混存）；
  - #J42 strategy_analyze _detect_market_state 改读真实 market_state 字段（原个股状态冒充）；
  - #J32 account_risk_status 连亏序列严格月份边界 + 零盈亏跳过不 break（Q5）；
  - #J33 account_risk_status 6% 未舍入比较（math.isclose 容差），舍入仅留展示（Q5）。
"""
import inspect
import os
import sys
from datetime import date
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest  # noqa: E402

# ══ #J33：6% 未舍入比较（Q5 拍板） ═══════════════════════════════

def test_j33_unrounded_comparison_no_false_halt():
    """raw=0.0599999 round(6)=0.06：未舍入比较不误停机（原逻辑 round 后误判 >= 6%）"""
    from app.services.account_risk_status import evaluate_monthly_risk_status

    s = evaluate_monthly_risk_status(month_pnl=-59_999.9, month_start_asset=1_000_000,
                                     consecutive_losses=0)
    assert s['monthly_loss_pct'] == 6.0          # 展示仍舍入为 6.0
    assert s['monthly_halt'] is False            # 但比较用未舍入值 → 不触发


def test_j33_exact_6pct_still_halts():
    """精确 6% 仍停机（回归 493 边界命中）"""
    from app.services.account_risk_status import evaluate_monthly_risk_status

    s = evaluate_monthly_risk_status(month_pnl=-60_000, month_start_asset=1_000_000,
                                     consecutive_losses=0)
    assert s['monthly_halt'] is True
    assert '月度亏损' in s['halt_reason']


def test_j33_isclose_edge_hits():
    """raw 距 0.06 差 1e-10：isclose 容差兜浮点误差 → 停机"""
    from app.services.account_risk_status import evaluate_monthly_risk_status

    s = evaluate_monthly_risk_status(month_pnl=-59_999.9999, month_start_asset=1_000_000,
                                     consecutive_losses=0)
    assert s['monthly_halt'] is True


def test_j33_display_still_rounded():
    """展示值仍按舍入输出（monthly_loss_pct 百分数两位）"""
    from app.services.account_risk_status import evaluate_monthly_risk_status

    s = evaluate_monthly_risk_status(month_pnl=-60_000, month_start_asset=1_000_000,
                                     consecutive_losses=0)
    assert s['monthly_loss_pct'] == 6.0
    assert s['monthly_loss_limit_pct'] == 6.0


# ══ #J32：连亏严格月份边界 + 零盈亏跳过（Q5 拍板） ════════════════

class _FakeQ:
    """模拟 query 链（filter/order_by 返回自身，all/first 返回预置行）"""
    def __init__(self, rows):
        self._rows = rows

    def filter(self, *a, **k):
        return self

    def order_by(self, *a, **k):
        return self

    def all(self):
        return self._rows

    def first(self):
        return self._rows[0] if self._rows else None


class _T:
    def __init__(self, d, pnl, direction='卖出', amount=100.0):
        self.trade_date = d
        self.realized_pnl = pnl
        self.direction = direction
        self.amount = amount


def test_j32_zero_pnl_not_break():
    """零盈亏卖出不中断连亏计数（原 pnl>=0 即 break → 连亏被错误截断）"""
    from app.services import account_risk_status as ars
    from sqlalchemy import Column, Date, Integer, String

    month_rows = [_T(date(2026, 10, 5), -1000.0), _T(date(2026, 10, 3), 0.0)]
    sells = [_T(date(2026, 10, 5), -1000.0),   # 最近卖出：亏损
             _T(date(2026, 10, 3), 0.0),        # 零盈亏：跳过不 break
             _T(date(2026, 10, 2), -2000.0)]    # 再往前：亏损
    all_trades = [_T(date(2026, 1, 1), 0.0, '买入', 50_000.0)]

    with mock.patch('app.models.trade.Trade') as MT, \
            mock.patch('app.models.trade.AccountSnapshot') as MS:
        # mock 类上挂真实列，使 trade_date >= month_start / .asc() 等表达式可构造
        MT.trade_date = Column(Date)
        MT.direction = Column(String(4))
        MT.id = Column(Integer)
        MS.snapshot_date = Column(Date)
        # ① 月内全部交易（month_pnl 累计） ③ 月内卖出（连亏）
        MT.query.filter.side_effect = [_FakeQ(month_rows), _FakeQ(sells)]
        # ② 无月初快照 → 走累计买入额
        MS.query.filter.return_value.order_by.return_value.first.return_value = None
        MT.query.order_by.return_value.all.return_value = all_trades

        s = ars.compute_from_account(today=date(2026, 10, 8))
        assert s['consecutive_losses'] == 2     # 零盈亏不 break（旧行为会停在 1）
        assert s['monthly_halt'] is False


def test_j32_month_boundary_in_source():
    """源码级断言：连亏 filter 含月份边界、零盈亏跳过分支存在"""
    from app.services import account_risk_status as ars

    src = inspect.getsource(ars.compute_from_account)
    assert 'trade_date >= month_start' in src
    assert '_pnl == 0' in src


# ══ #J34/#J35：opportunity_library 字段校验（先校验后 setattr） ════

def test_j35_coerce_numeric_fields():
    """数值列：数字串强制 cast、非法值/None/bool/dict 拒绝"""
    from app.routes.opportunity_library import _coerce_field

    assert _coerce_field('total_score', '12.5') == (12.5, None)
    assert _coerce_field('days_in_status', '7') == (7, None)
    assert _coerce_field('total_score', 'abc')[1] is not None
    assert _coerce_field('total_score', None)[1] is not None
    assert _coerce_field('total_score', {'a': 1})[1] is not None
    assert _coerce_field('total_score', True)[1] is not None
    assert _coerce_field('is_active', '0') == (0, None)


def test_j35_coerce_string_fields():
    """字符串/文本列：None 允许（可空列）、dict/list 拒绝、其余转 str"""
    from app.routes.opportunity_library import _coerce_field

    assert _coerce_field('name', None) == (None, None)
    assert _coerce_field('name', ['x'])[1] is not None
    assert _coerce_field('name', 123) == ('123', None)


def test_j34_lib_level_domain_before_setattr():
    """lib_level 域/null 校验前置（setattr 前拦截，非法值不入 ORM）"""
    from app.routes.opportunity_library import _coerce_field

    assert _coerce_field('lib_level', 'BAD')[1] is not None
    assert _coerce_field('lib_level', None)[1] is not None
    assert _coerce_field('lib_level', 'core') == ('core', None)
    assert _coerce_field('lib_level', 'scan') == ('scan', None)


def test_j36_rollback_in_write_endpoints():
    """写端点 commit 均包 try/except + rollback（防 PendingRollbackError 级联）"""
    from app.routes import opportunity_library as ol

    for fn in (ol.create_library_item, ol.update_library_item, ol.delete_library_item):
        src = inspect.getsource(fn)
        assert 'db.session.rollback()' in src
        assert 'try:' in src


def test_j37_escape_and_pagination():
    """search 转义 %/_ + ilike escape + 分页硬上限"""
    from app.routes import opportunity_library as ol

    src = inspect.getsource(ol.list_library)
    assert "replace('%', '\\\\%')" in src
    assert "escape='\\\\'" in src
    assert 'page_size' in src and 'min(100, page_size)' in src
    assert 'query.count()' in src


# ══ #J38/#J39：watchlist ════════════════════════════════════════

def test_j39_cache_module_singleton():
    """_get_cache() 返回模块级单例（原每次新建→缓存永不生效）"""
    from app.routes.watchlist import _get_cache

    a, b = _get_cache(), _get_cache()
    assert a is b


def test_j38_mf_sorted_single_row_no_nameerror():
    """单行 moneyflow + circ_mv>0：资金流不再被 NameError 吞掉（原 mf_sorted 未定义）"""
    import pandas as pd
    from app.routes.watchlist import _fetch_stock_quotes

    class _DM:
        def get_cached_daily_data(self, *a, **k):
            return pd.DataFrame()

        def get_cached_daily_basic(self, *a, **k):
            return pd.DataFrame({'ts_code': ['000001.SZ'], 'trade_date': ['2026-10-08'],
                                 'turnover_rate': [1.0], 'pe_ttm': [10.0], 'pe': [9.0],
                                 'pb': [1.5], 'circ_mv': [500_000.0], 'total_mv': [600_000.0]})

        def get_cached_moneyflow(self, **k):
            return pd.DataFrame({'trade_date': ['2026-10-08'],
                                 'buy_lg_amount': [100.0], 'sell_lg_amount': [50.0],
                                 'buy_elg_amount': [20.0], 'sell_elg_amount': [10.0],
                                 'buy_sm_amount': [5.0], 'sell_sm_amount': [2.0],
                                 'buy_lg_vol': [1000]})

        def get_fina_indicator(self, *a, **k):
            return []

        def get_stock_info(self, *a, **k):
            return {}

        def cache(self):
            class _C:
                def get_cached_stk_holder(self, *a):
                    return None

                def get_cached_top10_holders(self, *a):
                    return None
            return _C()

    stock = _fetch_stock_quotes('000001.SZ', _DM())
    assert stock['fund_net'] == 50.0            # 单行场景资金流正常产出（原整段被吞→None）
    assert stock['fund_add_td'] is not None     # 单行 + circ_mv>0 也正常
    assert stock['big_5d'] is None              # 单行无 5 日累计（分支未误入）


# ══ #J40：opportunity_atlas 惰性单例双检锁 ═══════════════════════

def test_j40_singleton_lock():
    """get_data_manager / _get_memory_cache 均单例且只构造一次（与测试执行顺序无关）"""
    from app.routes import opportunity_atlas as oa

    with mock.patch('app.routes.opportunity_atlas._data_manager', None), \
            mock.patch('app.data.DataManager') as MockDM:
        a, b = oa.get_data_manager(), oa.get_data_manager()
        assert a is b
        assert MockDM.call_count == 1

    with mock.patch('app.routes.opportunity_atlas._tm_cache', None), \
            mock.patch('app.data.memory_cache.TieredMemoryCache') as MockCache:
        c, d = oa._get_memory_cache(), oa._get_memory_cache()
        assert c is d
        assert MockCache.call_count == 1


def test_j40_lock_in_source():
    """惰性单例带 threading.Lock 双检锁"""
    from app.routes import opportunity_atlas as oa

    src = inspect.getsource(oa.get_data_manager) + inspect.getsource(oa._get_memory_cache)
    assert '_singleton_lock' in src
    assert 'with _singleton_lock:' in src


# ══ #J41/#J42：strategy_analyze ═════════════════════════════════

def test_j41_deep_chip_float_only():
    """deep_chip 统一仅存 float：无法数值化不混存（下游不再 str*float TypeError）"""
    from app.routes.strategy_analyze import _build_chip_dimension

    r = _build_chip_dimension(None, {'concentration': 'abc'})
    assert r['concentration'] == '--'           # 回归批次7 消费端守卫
    r2 = _build_chip_dimension(None, {'chip_peak': '12.5'})
    assert r2['avg_cost'] == 12.5               # 数字串 cast float
    r3 = _build_chip_dimension(None, {'concentration': 0.35})
    assert r3['concentration'] == '35.0%'       # 回归批次7 正常百分比


def test_j42_market_state_real_source():
    """市场状态读真实 market_state 字段（多数投票）；无则 UNKNOWN（不再个股状态冒充）"""
    from app.routes.strategy_analyze import _detect_market_state

    sigs = [
        {'market_state': 'TRENDING_BULL', 'status_recognition': {'state': 'ACCUMULATING'}},
        {'market_state': 'TRENDING_BULL', 'status_recognition': {'state': 'DISTRIBUTING'}},
        {'market_state': 'RANGING', 'status_recognition': {'state': 'ACCUMULATING'}},
    ]
    assert _detect_market_state(sigs) == 'TRENDING_BULL'    # 多数投票

    sigs2 = [{'status_recognition': {'state': 'ACCUMULATING'}}]
    assert _detect_market_state(sigs2) == 'UNKNOWN'         # 无真实源 → 诚实降级

    assert _detect_market_state([{'market_state': 'UNKNOWN'}]) == 'UNKNOWN'
