"""测试 ConflictArbiter 集成到 strategy_analyze 后的行为"""

from app.engine.framework.conflict_arbiter import ConflictArbiter


def test_conflict_arbiter_imported():
    """验证 ConflictArbiter 可导入"""
    assert ConflictArbiter is not None


def test_arbitrate_all_bullish():
    """全看涨信号 → final_signal=bullish"""
    arbiter = ConflictArbiter()
    signals = [
        {'strategy_name': '缠论走势分析', 'signal': 'bullish', 'confidence': 0.8},
        {'strategy_name': '量价分析策略', 'signal': 'bullish', 'confidence': 0.7},
        {'strategy_name': '筹码主力分析', 'signal': 'bullish', 'confidence': 0.6},
    ]
    result = arbiter.arbitrate(signals)
    assert result['final_signal'] == 'bullish'
    assert result['final_confidence'] >= 0.6
    assert 'arbitration_log' in result


def test_arbitrate_all_bearish():
    """全看跌信号 → final_signal=bearish"""
    arbiter = ConflictArbiter()
    signals = [
        {'strategy_name': '缠论走势分析', 'signal': 'bearish', 'confidence': 0.8},
        {'strategy_name': '量价分析策略', 'signal': 'bearish', 'confidence': 0.7},
    ]
    result = arbiter.arbitrate(signals)
    assert result['final_signal'] == 'bearish'
    assert result['final_confidence'] >= 0.6


def test_arbitrate_chanlun_overrides():
    """缠论 vs 其他：结构优先 — 仲裁日志包含结构优先记录"""
    arbiter = ConflictArbiter()
    signals = [
        {'strategy_name': '缠论走势分析', 'signal': 'bullish', 'confidence': 0.6},
        {'strategy_name': '筹码主力分析', 'signal': 'bearish', 'confidence': 0.8},
        {'strategy_name': 'BOCIASI快线', 'signal': 'bearish', 'confidence': 0.7},
    ]
    result = arbiter.arbitrate(signals)
    log_text = ' '.join(result.get('arbitration_log', []))
    assert '结构优先' in log_text


def test_arbitrate_empty():
    """空信号列表 → neutral"""
    arbiter = ConflictArbiter()
    result = arbiter.arbitrate([])
    assert result['final_signal'] == 'neutral'
    assert result['final_confidence'] == 0.0


def test_arbitrate_kronos_boost():
    """Kronos 确认多数方向 → 置信度增强"""
    arbiter = ConflictArbiter()
    signals = [
        {'strategy_name': '缠论走势分析', 'signal': 'bullish', 'confidence': 0.6},
        {'strategy_name': '量价分析策略', 'signal': 'bullish', 'confidence': 0.7},
    ]
    kronos = {'direction': 'bullish', 'confidence': 0.8, 'volatility_regime': 'normal'}
    result = arbiter.arbitrate(signals, kronos_result=kronos)
    log_text = ' '.join(result.get('arbitration_log', []))
    assert 'Kronos' in log_text
    assert '置信度增强' in log_text


def test_build_factor_dimension_arbitration():
    """验证 _build_factor_dimension 内部使用 ConflictArbiter"""
    from app.routes.strategy_analyze import _build_factor_dimension
    signals = [
        {'strategy_name': '缠论走势分析', 'signal': 'bullish', 'confidence': 0.8},
        {'strategy_name': '量价分析策略', 'signal': 'bullish', 'confidence': 0.7},
    ]
    result = _build_factor_dimension(signals)
    assert result['conflict_type'] == '一致'
    assert result['driving_factor'] == '缠论走势分析'
    assert 'arbitration_log' in result


def test_build_factor_dimension_conflict():
    """因子维度能够检测看涨和看空信号之间的冲突"""
    from app.routes.strategy_analyze import _build_factor_dimension
    signals = [
        {'strategy_name': '缠论走势分析', 'signal': 'bullish', 'confidence': 0.6},
        {'strategy_name': '筹码主力分析', 'signal': 'bearish', 'confidence': 0.8},
    ]
    result = _build_factor_dimension(signals)
    assert result['conflict_type'] == '严重分歧'
    assert len(result['conflict_items']) > 0


def test_build_factor_dimension_empty():
    """空信号 → 一致+中性"""
    from app.routes.strategy_analyze import _build_factor_dimension
    result = _build_factor_dimension([])
    assert result['conflict_type'] == '中性'
    assert result['driving_factor'] == ''


def test_get_latest_close():
    """提取最新收盘价"""
    from app.routes.strategy_analyze import _get_latest_close
    signals = [
        {'strategy_name': '缠论走势分析', 'latest_close': 15.5},
        {'strategy_name': '量价分析策略'},
    ]
    assert _get_latest_close(signals) == 15.5


def test_get_latest_close_none():
    """无收盘价时返回 None"""
    from app.routes.strategy_analyze import _get_latest_close
    assert _get_latest_close([]) is None
    assert _get_latest_close([{'strategy_name': '缠论走势分析'}]) is None
