"""
形态评分系统集成测试
=====================
测试完整流程：检测 → 聚合 → 缓存 → 集成

覆盖：
  - 完整评估流水线（detect → aggregate → evaluate）
  - 多种市场场景（上涨/下跌/震荡/极端）
  - 详情结构完整性
  - 形态属性一致性
  - 缓存集成（cache → retrieve round-trip）
  - 追踪器集成（tracker → engine 联动）
  - 边界条件与容错
"""
import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
for k in ['HTTP_PROXY', 'HTTPS_PROXY', 'ALL_PROXY']:
    os.environ.pop(k, None)

import pytest
import pandas as pd
import numpy as np
import sqlite3
import threading

from app.engine.patterns.engine import PatternEngine, WEIGHT_MAP
from app.engine.patterns import PatternResult, PatternCategory, PatternStage
from app.engine.patterns.tracker import PatternTracker


# ═══════════════════════════════════════════════════
# Fixtures — 多种市场场景
# ═══════════════════════════════════════════════════

@pytest.fixture
def uptrend_df():
    """创建上涨趋势 K 线数据（120 根日线）"""
    dates = pd.date_range(start='2025-01-01', periods=120, freq='D')
    np.random.seed(42)

    base = 100
    trend = np.linspace(0, 20, 120)
    noise = np.random.randn(120) * 3
    close = base + trend + noise

    open_price = close + np.random.randn(120) * 0.5
    high = np.maximum(close, open_price) + np.abs(np.random.randn(120) * 1.5)
    low = np.minimum(close, open_price) - np.abs(np.random.randn(120) * 1.5)

    # 上涨时放量
    base_vol = 2_000_000
    vol_trend = np.linspace(0, 1_000_000, 120)
    volume = base_vol + vol_trend + np.random.randn(120) * 500_000

    return pd.DataFrame({
        'open': open_price,
        'high': high,
        'low': low,
        'close': close,
        'volume': volume,
    }, index=dates)


@pytest.fixture
def downtrend_df():
    """创建下跌趋势 K 线数据"""
    dates = pd.date_range(start='2025-01-01', periods=120, freq='D')
    np.random.seed(123)

    base = 120
    trend = np.linspace(0, -30, 120)
    noise = np.random.randn(120) * 2.5
    close = base + trend + noise

    open_price = close + np.random.randn(120) * 0.5
    high = np.maximum(close, open_price) + np.abs(np.random.randn(120) * 1.0)
    low = np.minimum(close, open_price) - np.abs(np.random.randn(120) * 1.0)

    # 下跌时放量恐慌
    base_vol = 2_000_000
    vol_trend = np.linspace(0, 1_500_000, 120)
    volume = base_vol + vol_trend + np.random.randn(120) * 600_000

    return pd.DataFrame({
        'open': open_price,
        'high': high,
        'low': low,
        'close': close,
        'volume': volume,
    }, index=dates)


@pytest.fixture
def sideways_df():
    """创建震荡 K 线数据"""
    dates = pd.date_range(start='2025-01-01', periods=120, freq='D')
    np.random.seed(99)

    base = 100
    # 围绕均值小幅震荡
    noise = np.random.randn(120) * 2
    close = base + noise

    open_price = close + np.random.randn(120) * 0.3
    high = np.maximum(close, open_price) + np.abs(np.random.randn(120) * 0.8)
    low = np.minimum(close, open_price) - np.abs(np.random.randn(120) * 0.8)

    volume = 2_000_000 + np.random.randn(120) * 300_000

    return pd.DataFrame({
        'open': open_price,
        'high': high,
        'low': low,
        'close': close,
        'volume': volume,
    }, index=dates)


@pytest.fixture
def minimal_df():
    """最小可用 K 线（仅 5 根，触发边界逻辑）"""
    dates = pd.date_range(start='2025-01-01', periods=5, freq='D')
    return pd.DataFrame({
        'open':  [100, 101, 102, 103, 104],
        'high':  [101, 102, 103, 104, 105],
        'low':   [99,  100, 101, 102, 103],
        'close': [100.5, 101.5, 102.5, 103.5, 104.5],
        'volume': [1e6, 1.1e6, 1.2e6, 1.3e6, 1.4e6],
    }, index=dates)


@pytest.fixture
def empty_df():
    """空 DataFrame"""
    return pd.DataFrame()


@pytest.fixture
def ecm(tmp_path):
    """创建使用临时数据库的 EnhancedCacheManager 实例"""
    from app.data.enhanced_cache_manager import EnhancedCacheManager

    db_path = str(tmp_path / 'test_cache.db')
    compute_db_path = str(tmp_path / 'test_compute_cache.db')

    ecm = EnhancedCacheManager.__new__(EnhancedCacheManager)
    ecm._lock = threading.RLock()
    ecm._write_lock = threading.RLock()
    ecm._snapshot_write_lock = threading.RLock()

    class _FakeMC:
        def get(self, *a, **k): return None
        def put(self, *a, **k): pass
        def invalidate(self, *a, **k): pass
    ecm.memory_cache = _FakeMC()

    ecm.db_path = db_path
    ecm.conn = sqlite3.connect(db_path)
    ecm.conn.execute("PRAGMA journal_mode=WAL")
    ecm.read_conn = sqlite3.connect(db_path)
    ecm.read_conn.execute("PRAGMA journal_mode=WAL")

    # 356号方案：计算分库连接
    ecm.compute_db_path = compute_db_path
    ecm.compute_conn = sqlite3.connect(compute_db_path)
    ecm.compute_conn.execute("PRAGMA journal_mode=WAL")
    ecm.compute_read_conn = sqlite3.connect(compute_db_path)
    ecm.compute_read_conn.execute("PRAGMA journal_mode=WAL")

    # 建表（主库）
    ecm.conn.execute("""
        CREATE TABLE IF NOT EXISTS pattern_score_cache (
            ts_code TEXT NOT NULL,
            trade_date TEXT NOT NULL,
            score REAL NOT NULL,
            details_json TEXT NOT NULL,
            computed_at TEXT DEFAULT (datetime('now','localtime')),
            PRIMARY KEY (ts_code, trade_date)
        )
    """)
    ecm.conn.commit()

    # 建表（计算分库）
    ecm.compute_conn.execute("""
        CREATE TABLE IF NOT EXISTS pattern_score_cache (
            ts_code TEXT NOT NULL,
            trade_date TEXT NOT NULL,
            score REAL NOT NULL,
            details_json TEXT NOT NULL,
            computed_at TEXT DEFAULT (datetime('now','localtime')),
            PRIMARY KEY (ts_code, trade_date)
        )
    """)
    ecm.compute_conn.commit()

    ecm.cache_stats = {'hits_duckdb': 0, 'misses': 0, 'total_requests': 0}
    yield ecm
    ecm.conn.close()
    ecm.read_conn.close()
    ecm.compute_conn.close()
    ecm.compute_read_conn.close()


# ═══════════════════════════════════════════════════
# 1. 完整评估流水线
# ═══════════════════════════════════════════════════

class TestFullPipeline:
    """测试完整流程：detect → aggregate → evaluate"""

    def test_detect_all_returns_list(self, uptrend_df):
        """detect_all 应返回 PatternResult 列表"""
        engine = PatternEngine()
        patterns = engine.detect_all(uptrend_df)
        assert isinstance(patterns, list)

    def test_aggregate_returns_score_and_details(self, uptrend_df):
        """aggregate 应返回 (score, details) 元组"""
        engine = PatternEngine()
        patterns = engine.detect_all(uptrend_df)
        score, details = engine.aggregate(patterns)
        assert isinstance(score, float)
        assert isinstance(details, dict)

    def test_evaluate_is_detect_plus_aggregate(self, uptrend_df):
        """evaluate 应等于 detect_all + aggregate 的组合"""
        engine = PatternEngine()
        patterns = engine.detect_all(uptrend_df)
        score_a, details_a = engine.aggregate(patterns)

        score_e, details_e = engine.evaluate(uptrend_df)

        # evaluate 内部调用 detect_all + aggregate，结果应一致
        assert score_a == score_e
        assert details_a['pattern_count'] == details_e['pattern_count']

    def test_pipeline_with_downtrend(self, downtrend_df):
        """下跌趋势数据不崩溃"""
        engine = PatternEngine()
        score, details = engine.evaluate(downtrend_df)
        assert 0 <= score <= 10
        assert details['pattern_count'] >= 0

    def test_pipeline_with_sideways(self, sideways_df):
        """震荡数据不崩溃"""
        engine = PatternEngine()
        score, details = engine.evaluate(sideways_df)
        assert 0 <= score <= 10

    def test_pipeline_with_minimal_data(self, minimal_df):
        """最小数据量不崩溃"""
        engine = PatternEngine()
        score, details = engine.evaluate(minimal_df)
        assert 0 <= score <= 10

    def test_pipeline_with_empty_data(self, empty_df):
        """空数据应返回基础分"""
        engine = PatternEngine()
        score, details = engine.evaluate(empty_df)
        assert score == 5.0
        assert details['pattern_count'] == 0


# ═══════════════════════════════════════════════════
# 2. 分数范围与边界
# ═══════════════════════════════════════════════════

class TestScoreRange:
    """验证评分系统 0-10 分制约束"""

    def test_score_always_0_to_10_uptrend(self, uptrend_df):
        """上涨趋势评分在 [0, 10]"""
        engine = PatternEngine()
        score, _ = engine.evaluate(uptrend_df)
        assert 0 <= score <= 10

    def test_score_always_0_to_10_downtrend(self, downtrend_df):
        """下跌趋势评分在 [0, 10]"""
        engine = PatternEngine()
        score, _ = engine.evaluate(downtrend_df)
        assert 0 <= score <= 10

    def test_score_always_0_to_10_sideways(self, sideways_df):
        """震荡趋势评分在 [0, 10]"""
        engine = PatternEngine()
        score, _ = engine.evaluate(sideways_df)
        assert 0 <= score <= 10

    def test_empty_patterns_yield_base_score(self):
        """无形态输入 = 基础分 5.0"""
        engine = PatternEngine()
        score, _ = engine.aggregate([])
        assert score == 5.0

    def test_score_clamped_at_upper_bound(self):
        """大量强力看涨形态时分数不超过 10"""
        engine = PatternEngine()
        patterns = [
            PatternResult(
                name=f'P-3-{i}',
                category=PatternCategory.BLACKHORSE,
                direction='bullish',
                strength=1.0,
                stage=PatternStage.COMPLETED,
                completion=1.0,
            )
            for i in range(1, 11)
        ]
        score, _ = engine.aggregate(patterns)
        assert score == 10.0

    def test_score_clamped_at_lower_bound(self):
        """大量强力看跌形态时分数不低于 0"""
        engine = PatternEngine()
        patterns = [
            PatternResult(
                name=f'P-2-{i}',
                category=PatternCategory.BEARISH_PATTERNS,
                direction='bearish',
                strength=1.0,
                stage=PatternStage.COMPLETED,
                completion=1.0,
            )
            for i in range(1, 21)
        ]
        score, _ = engine.aggregate(patterns)
        assert score == 0.0


# ═══════════════════════════════════════════════════
# 3. 详情结构完整性
# ═══════════════════════════════════════════════════

class TestDetailsStructure:
    """验证聚合结果的详情字典结构"""

    def test_details_has_required_keys(self, uptrend_df):
        """详情必须包含核心字段"""
        engine = PatternEngine()
        _, details = engine.evaluate(uptrend_df)
        required = ['bull_count', 'bear_count', 'pattern_count',
                     'bull_strength_avg', 'bear_strength_avg', 'patterns']
        for key in required:
            assert key in details, f"缺少字段: {key}"

    def test_details_counts_are_non_negative(self, uptrend_df):
        """计数字段不能为负"""
        engine = PatternEngine()
        _, details = engine.evaluate(uptrend_df)
        assert details['bull_count'] >= 0
        assert details['bear_count'] >= 0
        assert details['pattern_count'] >= 0

    def test_details_pattern_count_matches_list(self, uptrend_df):
        """pattern_count 应等于 patterns 列表长度"""
        engine = PatternEngine()
        _, details = engine.evaluate(uptrend_df)
        assert details['pattern_count'] == len(details['patterns'])

    def test_details_strength_avg_is_valid(self, uptrend_df):
        """强度均值应在 [0, 1] 范围"""
        engine = PatternEngine()
        _, details = engine.evaluate(uptrend_df)
        if details['bull_count'] > 0:
            assert 0 <= details['bull_strength_avg'] <= 1
        if details['bear_count'] > 0:
            assert 0 <= details['bear_strength_avg'] <= 1

    def test_details_patterns_list_structure(self, uptrend_df):
        """patterns 列表中每个元素应有 name/direction/strength"""
        engine = PatternEngine()
        _, details = engine.evaluate(uptrend_df)
        for p in details['patterns']:
            assert 'name' in p
            assert 'direction' in p
            assert 'strength' in p

    def test_details_empty_patterns(self):
        """无形态时详情结构正确"""
        engine = PatternEngine()
        _, details = engine.aggregate([])
        assert details['pattern_count'] == 0
        assert details['bull_count'] == 0
        assert details['bear_count'] == 0
        assert details['patterns'] == []


# ═══════════════════════════════════════════════════
# 4. 形态属性一致性
# ═══════════════════════════════════════════════════

class TestPatternProperties:
    """验证检测出的 PatternResult 属性合法"""

    def test_patterns_have_valid_direction(self, uptrend_df):
        """所有形态方向必须是 bullish/bearish/neutral"""
        engine = PatternEngine()
        patterns = engine.detect_all(uptrend_df)
        for p in patterns:
            assert p.direction in ('bullish', 'bearish', 'neutral'), \
                f"无效方向: {p.direction} (形态 {p.name})"

    def test_patterns_have_valid_strength(self, uptrend_df):
        """所有形态强度必须在 [0, 1]"""
        engine = PatternEngine()
        patterns = engine.detect_all(uptrend_df)
        for p in patterns:
            assert 0 <= p.strength <= 1, \
                f"强度越界: {p.strength} (形态 {p.name})"

    def test_patterns_have_name(self, uptrend_df):
        """所有形态必须有非空名称"""
        engine = PatternEngine()
        patterns = engine.detect_all(uptrend_df)
        for p in patterns:
            assert p.name, f"形态名称为空"
            assert len(p.name) >= 2

    def test_patterns_have_category(self, uptrend_df):
        """所有形态必须有合法分类"""
        engine = PatternEngine()
        patterns = engine.detect_all(uptrend_df)
        valid_cats = set(PatternCategory)
        for p in patterns:
            assert p.category in valid_cats, \
                f"无效分类: {p.category} (形态 {p.name})"

    def test_patterns_have_stage(self, uptrend_df):
        """所有形态必须有合法生命周期阶段"""
        engine = PatternEngine()
        patterns = engine.detect_all(uptrend_df)
        valid_stages = set(PatternStage)
        for p in patterns:
            assert p.stage in valid_stages, \
                f"无效阶段: {p.stage} (形态 {p.name})"

    def test_patterns_have_completion(self, uptrend_df):
        """所有形态完成度在 [0, 100]"""
        engine = PatternEngine()
        patterns = engine.detect_all(uptrend_df)
        for p in patterns:
            assert 0 <= p.completion <= 100, \
                f"完成度越界: {p.completion} (形态 {p.name})"

    def test_pattern_to_dict_roundtrip(self, uptrend_df):
        """PatternResult.to_dict() 应返回可序列化字典"""
        engine = PatternEngine()
        patterns = engine.detect_all(uptrend_df)
        for p in patterns:
            d = p.to_dict()
            assert isinstance(d, dict)
            assert 'name' in d
            assert 'category' in d
            assert 'direction' in d
            assert 'strength' in d

    def test_detect_downward_has_bearish(self, downtrend_df):
        """下跌趋势应检测到看跌形态（或无形态）"""
        engine = PatternEngine()
        patterns = engine.detect_all(downtrend_df)
        # 不强制有 bearish，但如有则方向正确
        for p in patterns:
            if p.name.startswith('P-2-'):
                assert p.direction == 'bearish'


# ═══════════════════════════════════════════════════
# 5. 权重与加权计算一致性
# ═══════════════════════════════════════════════════

class TestWeightConsistency:
    """验证 WEIGHT_MAP 与实际聚合逻辑一致"""

    def test_weight_map_covers_all_wiki_patterns(self):
        """权重表覆盖 58 种形态+状态"""
        # 预涨型 20
        for i in range(1, 21):
            assert f'P-1-{i}' in WEIGHT_MAP
        # 预跌型 20
        for i in range(1, 21):
            assert f'P-2-{i}' in WEIGHT_MAP
        # 黑马型 10
        for i in range(1, 11):
            assert f'P-3-{i}' in WEIGHT_MAP
        # 状态 8
        for i in range(1, 9):
            assert f'S-{i}' in WEIGHT_MAP
        assert len(WEIGHT_MAP) == 58

    def test_bullish_adds_to_score(self):
        """单个看涨形态应提升分数"""
        engine = PatternEngine()
        p = PatternResult(
            name='P-1-1', category=PatternCategory.BULLISH_PATTERNS,
            direction='bullish', strength=0.8,
            stage=PatternStage.COMPLETED, completion=1.0,
        )
        score, _ = engine.aggregate([p])
        assert score > 5.0

    def test_bearish_subtracts_from_score(self):
        """单个看跌形态应降低分数"""
        engine = PatternEngine()
        p = PatternResult(
            name='P-2-1', category=PatternCategory.BEARISH_PATTERNS,
            direction='bearish', strength=0.8,
            stage=PatternStage.COMPLETED, completion=1.0,
        )
        score, _ = engine.aggregate([p])
        assert score < 5.0

    def test_blackhorse_gets_extra_multiplier(self):
        """黑马型权重比普通看涨更高（1.5x 额外加权）"""
        engine = PatternEngine()
        blackhorse = PatternResult(
            name='P-3-1', category=PatternCategory.BLACKHORSE,
            direction='bullish', strength=1.0,
            stage=PatternStage.COMPLETED, completion=1.0,
        )
        regular = PatternResult(
            name='P-1-1', category=PatternCategory.BULLISH_PATTERNS,
            direction='bullish', strength=1.0,
            stage=PatternStage.COMPLETED, completion=1.0,
        )
        score_bh, _ = engine.aggregate([blackhorse])
        score_reg, _ = engine.aggregate([regular])
        # P-3-1 weight=5.0 * 1.5 = 7.5, P-1-1 weight=3.0
        assert score_bh > score_reg

    def test_multi_bullish_resonance_bonus(self):
        """≥3 个同向看涨形态触发共振加分"""
        engine = PatternEngine()
        patterns = [
            PatternResult(
                name=f'P-1-{i}', category=PatternCategory.BULLISH_PATTERNS,
                direction='bullish', strength=0.3,
                stage=PatternStage.COMPLETED, completion=1.0,
            )
            for i in range(1, 4)
        ]
        score, details = engine.aggregate(patterns)
        assert details['bull_count'] == 3
        # 低强度下仅靠共振可能不够明显，但计数应正确
        assert score >= 5.0

    def test_multi_bearish_resonance_penalty(self):
        """≥3 个同向看跌形态触发共振减分"""
        engine = PatternEngine()
        patterns = [
            PatternResult(
                name=f'P-2-{i}', category=PatternCategory.BEARISH_PATTERNS,
                direction='bearish', strength=0.3,
                stage=PatternStage.COMPLETED, completion=1.0,
            )
            for i in range(1, 4)
        ]
        score, details = engine.aggregate(patterns)
        assert details['bear_count'] == 3
        assert score <= 5.0

    def test_neutral_patterns_do_not_affect_score(self):
        """中性形态不影响评分"""
        engine = PatternEngine()
        p = PatternResult(
            name='neutral_pattern', category=PatternCategory.CANDLESTICK,
            direction='neutral', strength=1.0,
            stage=PatternStage.COMPLETED, completion=1.0,
        )
        score, details = engine.aggregate([p])
        assert score == 5.0
        assert details['bull_count'] == 0
        assert details['bear_count'] == 0


# ═══════════════════════════════════════════════════
# 6. 缓存集成
# ═══════════════════════════════════════════════════

class TestCacheIntegration:
    """测试引擎产出 → 缓存读写 round-trip"""

    def test_engine_to_cache_roundtrip(self, ecm, uptrend_df):
        """引擎评估结果可正确缓存并取回"""
        engine = PatternEngine()
        score, details = engine.evaluate(uptrend_df)

        ts_code = '000001.SZ'
        trade_date = '2025-08-15'
        ecm.cache_pattern_score(ts_code, trade_date, score, details)

        result = ecm.get_pattern_score(ts_code, trade_date)
        assert result is not None
        assert result['score'] == score
        assert result['details']['pattern_count'] == details['pattern_count']
        assert result['details']['bull_count'] == details['bull_count']
        assert result['details']['bear_count'] == details['bear_count']

    def test_cache_preserves_patterns_list(self, ecm, uptrend_df):
        """缓存后形态列表完整保留"""
        engine = PatternEngine()
        score, details = engine.evaluate(uptrend_df)

        ecm.cache_pattern_score('000001.SZ', '2025-08-15', score, details)
        result = ecm.get_pattern_score('000001.SZ', '2025-08-15')

        cached_patterns = result['details']['patterns']
        assert len(cached_patterns) == details['pattern_count']
        for i, p in enumerate(cached_patterns):
            assert p['name'] == details['patterns'][i]['name']
            assert p['direction'] == details['patterns'][i]['direction']
            assert abs(p['strength'] - details['patterns'][i]['strength']) < 1e-9

    def test_cache_overwrite(self, ecm):
        """同一 key 重复写入应覆盖"""
        ecm.cache_pattern_score('000001.SZ', '2025-08-15', 3.0, {'v': 1})
        ecm.cache_pattern_score('000001.SZ', '2025-08-15', 8.0, {'v': 2})
        result = ecm.get_pattern_score('000001.SZ', '2025-08-15')
        assert result['score'] == 8.0

    def test_cache_multiple_stocks(self, ecm, uptrend_df, downtrend_df):
        """不同股票的缓存互不干扰"""
        engine = PatternEngine()
        score_u, details_u = engine.evaluate(uptrend_df)
        score_d, details_d = engine.evaluate(downtrend_df)

        ecm.cache_pattern_score('000001.SZ', '2025-08-15', score_u, details_u)
        ecm.cache_pattern_score('600000.SH', '2025-08-15', score_d, details_d)

        r1 = ecm.get_pattern_score('000001.SZ', '2025-08-15')
        r2 = ecm.get_pattern_score('600000.SH', '2025-08-15')
        assert r1['score'] == score_u
        assert r2['score'] == score_d
        assert r1['score'] != r2['score']  # 不同市场数据不同分

    def test_has_pattern_score(self, ecm, uptrend_df):
        """has_pattern_score 应正确反映缓存存在性"""
        engine = PatternEngine()
        score, details = engine.evaluate(uptrend_df)

        assert ecm.has_pattern_score('000001.SZ', '2025-08-15') is False
        ecm.cache_pattern_score('000001.SZ', '2025-08-15', score, details)
        assert ecm.has_pattern_score('000001.SZ', '2025-08-15') is True


# ═══════════════════════════════════════════════════
# 7. 追踪器集成
# ═══════════════════════════════════════════════════

class TestTrackerIntegration:
    """测试 PatternTracker 与引擎检测结果的联动"""

    def test_tracker_can_track_detected_patterns(self, uptrend_df):
        """引擎检测的形态可被追踪器追踪"""
        engine = PatternEngine()
        tracker = PatternTracker()

        patterns = engine.detect_all(uptrend_df)
        for p in patterns:
            tracker.track(p)

        active = tracker.get_active()
        # 所有 track 的形态应处于 FORMING 阶段
        for p in active:
            assert p.stage == PatternStage.FORMING

    def test_tracker_does_not_duplicate(self, uptrend_df):
        """重复 track 同名形态不应创建多个"""
        engine = PatternEngine()
        tracker = PatternTracker()

        patterns = engine.detect_all(uptrend_df)
        if patterns:
            tracker.track(patterns[0])
            tracker.track(patterns[0])  # 重复
            active = tracker.get_active()
            names = [p.name for p in active]
            assert len(names) == len(set(names))

    def test_tracker_update_on_new_data(self, uptrend_df):
        """新数据到来时 tracker 更新状态"""
        engine = PatternEngine()
        tracker = PatternTracker()

        # 取前 60 根检测并追踪
        df_half = uptrend_df.iloc[:60]
        patterns = engine.detect_all(df_half)
        for p in patterns:
            tracker.track(p)

        # 用全部数据更新
        updates = tracker.update(uptrend_df)
        assert isinstance(updates, list)

    def test_tracker_reset_clears_state(self, uptrend_df):
        """reset 应清除所有追踪状态"""
        engine = PatternEngine()
        tracker = PatternTracker()

        patterns = engine.detect_all(uptrend_df)
        for p in patterns:
            tracker.track(p)

        tracker.reset()
        assert len(tracker.get_active()) == 0
        assert len(tracker.get_completed()) == 0

    def test_tracker_history_grows(self):
        """手动 untrack 的形态进入历史记录（FORMING 阶段）"""
        tracker = PatternTracker()
        p = PatternResult(
            name='test_pattern', category=PatternCategory.CANDLESTICK,
            direction='bullish', strength=0.5,
            stage=PatternStage.COMPLETED, completion=100.0,
        )
        tracker.track(p)
        # track() 将 stage 改为 FORMING
        assert p.stage == PatternStage.FORMING

        tracker.untrack('test_pattern')

        # untrack 移入 history
        assert len(tracker.history) >= 1
        assert tracker.history[-1].name == 'test_pattern'
        # get_completed 只返回 COMPLETED 阶段，FORMING 不应出现
        assert len(tracker.get_completed()) == 0


# ═══════════════════════════════════════════════════
# 8. 多场景对比
# ═══════════════════════════════════════════════════

class TestMultiScenarioComparison:
    """对比不同市场场景下的评分表现"""

    def test_engine_works_across_all_scenarios(self, uptrend_df, downtrend_df, sideways_df):
        """三种市场数据均能完成评估而不崩溃"""
        engine = PatternEngine()
        for df in [uptrend_df, downtrend_df, sideways_df]:
            score, details = engine.evaluate(df)
            assert 0 <= score <= 10
            assert 'pattern_count' in details

    def test_score_deterministic_for_same_input(self, uptrend_df):
        """相同输入多次评估应得到相同结果"""
        engine = PatternEngine()
        s1, d1 = engine.evaluate(uptrend_df)
        s2, d2 = engine.evaluate(uptrend_df)
        assert s1 == s2
        assert d1['pattern_count'] == d2['pattern_count']
        assert d1['bull_count'] == d2['bull_count']
        assert d1['bear_count'] == d2['bear_count']

    def test_different_engines_same_result(self, uptrend_df):
        """不同 PatternEngine 实例对同一数据应一致"""
        e1 = PatternEngine()
        e2 = PatternEngine()
        s1, _ = e1.evaluate(uptrend_df)
        s2, _ = e2.evaluate(uptrend_df)
        assert s1 == s2

    def test_mixed_bull_bear_patterns_score(self):
        """看涨+看跌混合时分数应在中间区间"""
        engine = PatternEngine()
        patterns = [
            PatternResult(
                name='P-1-1', category=PatternCategory.BULLISH_PATTERNS,
                direction='bullish', strength=0.5,
                stage=PatternStage.COMPLETED, completion=1.0,
            ),
            PatternResult(
                name='P-2-1', category=PatternCategory.BEARISH_PATTERNS,
                direction='bearish', strength=0.5,
                stage=PatternStage.COMPLETED, completion=1.0,
            ),
        ]
        score, details = engine.aggregate(patterns)
        # 一个 bullish (+1.5) 和一个 bearish (-1.5)，互相抵消回 5.0
        assert details['bull_count'] == 1
        assert details['bear_count'] == 1
        assert abs(score - 5.0) < 0.1  # 应接近基础分


# ═══════════════════════════════════════════════════
# 9. 引擎初始化与组件连通性
# ═══════════════════════════════════════════════════

class TestEngineInitialization:
    """验证引擎各组件正确初始化"""

    def test_engine_has_all_detectors(self):
        """引擎应包含四种检测器"""
        engine = PatternEngine()
        assert engine.bullish_detector is not None
        assert engine.bearish_detector is not None
        assert engine.blackhorse_detector is not None
        assert engine.state_detector is not None

    def test_engine_has_registry(self):
        """引擎应有注册表"""
        engine = PatternEngine()
        assert engine.registry is not None

    def test_engine_is_reentrant(self, uptrend_df):
        """同一引擎可多次调用，状态不串扰"""
        engine = PatternEngine()
        s1, d1 = engine.evaluate(uptrend_df)
        s2, d2 = engine.evaluate(uptrend_df)
        assert s1 == s2
        assert d1 == d2
