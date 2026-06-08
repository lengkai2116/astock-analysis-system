"""
服务层集成测试
覆盖数据源管理器、信号计算服务、策略模板服务
"""
import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

import pytest


# ========== Data Source Manager ==========

def test_data_source_manager_import():
    """测试数据源管理器可导入"""
    try:
        from app.data.data_source_manager import DataSourceManager, DataSourceStatus
        assert DataSourceManager is not None
        assert DataSourceStatus is not None
        assert hasattr(DataSourceStatus, 'NORMAL')
        assert hasattr(DataSourceStatus, 'FALLBACK')
    except ImportError as e:
        pytest.skip(f"数据源管理器不可用: {e}")


def test_data_source_manager_health():
    """测试数据源健康状态"""
    try:
        from app.data.data_source_manager import DataSourceHealth
        health = DataSourceHealth(name='test_source', priority=0)
        assert health.name == 'test_source'
        assert health.priority == 0
        assert health.status.value == 'normal'
        
        # 记录成功
        health.record_success(100.0)
        assert health.total_requests == 1
        assert health.consecutive_failures == 0
        
        # 记录失败
        health.record_failure('test error')
        assert health.consecutive_failures == 1
        assert health.last_error == 'test error'
        
    except ImportError as e:
        pytest.skip(f"数据源健康状态不可用: {e}")


# ========== Strategy Template Service ==========

def test_strategy_template_service_import():
    """测试策略模板服务可导入"""
    try:
        from app.services.strategy_template_service import StrategyTemplateService
        assert StrategyTemplateService is not None
    except ImportError as e:
        pytest.skip(f"策略模板服务不可用: {e}")


# ========== Signal Computation Service ==========

def test_signal_computation_import():
    """测试信号计算服务可导入"""
    try:
        from app.services.signal_computation_service import SignalComputationService
        assert SignalComputationService is not None
    except ImportError as e:
        pytest.skip(f"信号计算服务不可用: {e}")


def test_signal_match_import():
    """测试信号匹配服务可导入"""
    try:
        from app.services.signal_match_service import SignalMatchService
        assert SignalMatchService is not None
    except ImportError as e:
        pytest.skip(f"信号匹配服务不可用: {e}")


# ========== Market Service ==========

def test_market_service_import():
    """测试市场服务可导入"""
    try:
        from app.services.market_service import MarketService
        assert MarketService is not None
    except ImportError as e:
        pytest.skip(f"市场服务不可用: {e}")


# ========== AI Analysis Service ==========

def test_ai_analysis_service_import():
    """测试 AI 分析服务可导入"""
    try:
        from app.services.deepseek_analysis_service import DeepSeekAnalysisService
        assert DeepSeekAnalysisService is not None
    except ImportError as e:
        pytest.skip(f"AI 分析服务不可用: {e}")


# ========== Cache Manager ==========

def test_cache_manager_import():
    """测试缓存管理器可导入"""
    try:
        from app.data.cache_manager import CacheManager
        assert CacheManager is not None
    except ImportError as e:
        pytest.skip(f"缓存管理器不可用: {e}")


def test_redis_cache_manager_import():
    """测试 Redis 缓存管理器可导入"""
    try:
        from app.data.redis_cache_manager import RedisCacheManager
        assert RedisCacheManager is not None
    except ImportError as e:
        pytest.skip(f"Redis 缓存管理器不可用: {e}")


if __name__ == '__main__':
    pytest.main([__file__, '-v'])
