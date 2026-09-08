"""417号方案回归测试：COL 采集端深度数据清洗

覆盖 4 项增强：
- 增强1：数值列 to_numeric + 按表类型 NaN 处理（K线价格 NaN→0、财务表 NaN→NULL）
- 增强2：OHLC 一致性校验（high/low 交换、open/close 夹取、全 0 丢弃）
- 增强3：离群值检测（|pct_chg|>50 剔除）
- 增强4：清洗可观测性（剔除行数日志）

测试直接调用 EnhancedCacheManager 的清洗方法（_apply_deep_clean / _fix_ohlc /
_detect_outliers），不依赖真实 DB 数据，避免外部服务依赖。
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
for k in ['HTTP_PROXY', 'HTTPS_PROXY', 'ALL_PROXY']:
    os.environ.pop(k, None)

import pandas as pd
import pytest


@pytest.fixture(scope='module')
def ecm():
    from app.data.enhanced_cache_manager import EnhancedCacheManager
    return EnhancedCacheManager()


# ── 增强1：数值列 to_numeric + NaN 处理 ─────────────────────

def test_kline_numeric_nan_to_zero(ecm):
    """K线表：非 OHLC 数值列 NaN → 0（与 _safe_float 一致）

    注：价格列（open/high/low/close）NaN 会被规则5 OHLC 校验剔除（价格缺失行
    本就无效），故此处验证 vol/amount 等量额列的 NaN→0。
    """
    df = pd.DataFrame({
        'ts_code': ['000001.SZ', '600000.SH'],
        'trade_date': ['2026-09-08', '2026-09-08'],
        'open': [10.0, 10.0],
        'high': [11.0, 12.0],
        'low': [9.0, 11.0],
        'close': [10.5, 11.5],
        'vol': [1000, None],
        'amount': [None, 5000],
        'pct_chg': [1.0, 2.0],
    })
    out = ecm._apply_deep_clean('daily_cache', df)
    # NaN → 0
    assert out['vol'].iloc[1] == 0.0, "K线 vol NaN 应填 0"
    assert out['amount'].iloc[0] == 0.0, "K线 amount NaN 应填 0"
    # 数值列类型统一
    assert pd.api.types.is_numeric_dtype(out['open']), "open 应为数值类型"


def test_financial_nan_kept_null(ecm):
    """财务表：数值列 NaN 保留（不伪造 0）"""
    df = pd.DataFrame({
        'ts_code': ['000001.SZ'],
        'end_date': ['2026-06-30'],
        'pe': [None],
        'pb': [1.5],
        'total_mv': [None],
    })
    out = ecm._apply_deep_clean('daily_basic_cache', df)
    # NaN 保留（落库为 NULL）
    assert pd.isna(out['pe'].iloc[0]), "财务表 pe NaN 应保留（NULL）"
    assert pd.isna(out['total_mv'].iloc[0]), "财务表 total_mv NaN 应保留（NULL）"
    # 非 NaN 值保留
    assert out['pb'].iloc[0] == 1.5, "pb 正常值应保留"


def test_numeric_type_conversion(ecm):
    """数值列类型统一：字符串数字 → 数值"""
    df = pd.DataFrame({
        'ts_code': ['000001.SZ'],
        'trade_date': ['2026-09-08'],
        'open': ['10.5'],
        'high': ['11.0'],
        'low': ['10.0'],
        'close': ['10.8'],
        'vol': ['1000'],
        'amount': ['5000'],
        'pct_chg': ['1.2'],
    })
    out = ecm._apply_deep_clean('daily_cache', df)
    assert pd.api.types.is_numeric_dtype(out['open']), "open 字符串应转数值"
    assert out['open'].iloc[0] == 10.5, "open 转换值应正确"


# ── 增强2：OHLC 一致性校验 ─────────────────────────────────

def test_ohlc_high_low_swap(ecm):
    """high < low → 交换"""
    df = pd.DataFrame({
        'ts_code': ['000001.SZ'],
        'trade_date': ['2026-09-08'],
        'open': [10.0], 'high': [9.0], 'low': [11.0], 'close': [10.5],
        'vol': [1000], 'amount': [5000], 'pct_chg': [1.0],
    })
    out = ecm._fix_ohlc(df)
    assert out['high'].iloc[0] >= out['low'].iloc[0], "high 应 >= low（交换后）"
    assert out['high'].iloc[0] == 11.0, "high 应为原 low 值"
    assert out['low'].iloc[0] == 9.0, "low 应为原 high 值"


def test_ohlc_open_close_clip(ecm):
    """open/close 超出 [low, high] → 夹取到区间"""
    df = pd.DataFrame({
        'ts_code': ['000001.SZ'],
        'trade_date': ['2026-09-08'],
        'open': [5.0], 'high': [11.0], 'low': [9.0], 'close': [15.0],
        'vol': [1000], 'amount': [5000], 'pct_chg': [1.0],
    })
    out = ecm._fix_ohlc(df)
    assert out['open'].iloc[0] == 9.0, "open 应夹取到 low"
    assert out['close'].iloc[0] == 11.0, "close 应夹取到 high"


def test_ohlc_all_zero_dropped(ecm):
    """全部价格 <= 0 → 丢弃该行"""
    df = pd.DataFrame({
        'ts_code': ['000001.SZ', '600000.SH'],
        'trade_date': ['2026-09-08', '2026-09-08'],
        'open': [0.0, 10.0], 'high': [0.0, 11.0], 'low': [0.0, 9.0], 'close': [0.0, 10.5],
        'vol': [0, 1000], 'amount': [0, 5000], 'pct_chg': [0.0, 1.0],
    })
    out = ecm._fix_ohlc(df)
    assert len(out) == 1, "全 0 行应被丢弃"
    assert out['ts_code'].iloc[0] == '600000.SH', "应保留有效行"


# ── 增强3：离群值检测 ─────────────────────────────────────

def test_outlier_pct_chg_dropped(ecm):
    """|pct_chg| > 50 → 剔除"""
    df = pd.DataFrame({
        'ts_code': ['000001.SZ', '600000.SH', '000002.SZ'],
        'trade_date': ['2026-09-08', '2026-09-08', '2026-09-08'],
        'open': [10.0, 10.0, 10.0], 'high': [11.0, 11.0, 11.0],
        'low': [9.0, 9.0, 9.0], 'close': [10.5, 10.5, 10.5],
        'vol': [1000, 1000, 1000], 'amount': [5000, 5000, 5000],
        'pct_chg': [1.0, 60.0, -55.0],
    })
    out = ecm._detect_outliers(df)
    assert len(out) == 1, "2 条超限记录应被剔除"
    assert out['ts_code'].iloc[0] == '000001.SZ', "应保留正常记录"


def test_outlier_normal_kept(ecm):
    """正常涨跌幅（含新股/ST 大波动）保留"""
    df = pd.DataFrame({
        'ts_code': ['000001.SZ'],
        'trade_date': ['2026-09-08'],
        'open': [10.0], 'high': [11.0], 'low': [9.0], 'close': [10.5],
        'vol': [1000], 'amount': [5000], 'pct_chg': [44.0],
    })
    out = ecm._detect_outliers(df)
    assert len(out) == 1, "44% 涨跌幅（新股/ST 场景）应保留"


# ── 增强4：清洗可观测性（剔除行数日志）────────────────────

def test_clean_observability_log(caplog):
    """深度清洗剔除行数差异 → 输出告警日志"""
    from app.data.enhanced_cache_manager import EnhancedCacheManager
    ecm = EnhancedCacheManager()
    df = pd.DataFrame({
        'ts_code': ['000001.SZ', '600000.SH'],
        'trade_date': ['2026-09-08', '2026-09-08'],
        'open': [10.0, 0.0], 'high': [11.0, 0.0], 'low': [9.0, 0.0], 'close': [10.5, 0.0],
        'vol': [1000, 0], 'amount': [5000, 0], 'pct_chg': [1.0, 0.0],
    })
    with caplog.at_level('WARNING'):
        ecm._insert_from_df('daily_cache', df)
    assert any('[COL清洗]' in r.message for r in caplog.records), "应输出 COL清洗 告警日志"
