"""
push_service 单元测试（迭代2：API 定时推送）
===========================================
测试推服务的纯函数计算逻辑，不依赖真实的 SocketIO / ECManager。
推送函数通过 mock 验证 emit 行为。
"""
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

import importlib.util
from unittest.mock import MagicMock, patch, PropertyMock

# ══════════════════════════════════════════════════════════════
# 直接加载 push_service 模块（绕过 app 包完整导入链）
# ══════════════════════════════════════════════════════════════

_push_module_path = os.path.join(
    os.path.dirname(__file__), '..', 'app', 'services', 'push_service.py'
)
_spec = importlib.util.spec_from_file_location('_push_test_mod', _push_module_path)
push_svc = importlib.util.module_from_spec(_spec)
sys.modules['_push_test_mod'] = push_svc
_spec.loader.exec_module(push_svc)


# ══════════════════════════════════════════════════════════════
# 工具函数测试
# ══════════════════════════════════════════════════════════════


def test_compute_change_pct():
    """测试涨跌幅计算函数"""
    f = push_svc._compute_change_pct

    # 上涨 5%
    assert f({'price': 10.5, 'prev_close': 10.0}) == 5.0

    # 持平
    assert f({'price': 10.0, 'prev_close': 10.0}) == 0.0

    # 下跌 5%
    assert f({'price': 9.5, 'prev_close': 10.0}) == -5.0

    # prev_close 为零 → 返回 0（无法计算）
    assert f({'price': 10.0, 'prev_close': 0}) == 0.0

    # 缺失 prev_close → 返回 0
    assert f({'price': 10.0}) == 0.0

    # 缺失 price → price=0, prev_close=10 → (0-10)/10*100 = -100%
    assert f({'prev_close': 10.0}) == -100.0

    # 空字典
    assert f({}) == 0.0

    print("✅ test_compute_change_pct PASSED")


def test_get_cached_at():
    """测试 cached_at 时间戳提取"""
    f = push_svc._get_cached_at

    # 空列表
    assert f([]) == ''

    # 正常提取
    assert f([{'cached_at': '2026-07-10 14:30:00'}]) == '2026-07-10 14:30:00'

    # 取第一条
    assert f([
        {'cached_at': '2026-07-10 14:30:05'},
        {'cached_at': '2026-07-10 14:30:00'},
    ]) == '2026-07-10 14:30:05'

    # 无 cached_at 字段
    assert f([{'price': 10.0}]) == ''

    print("✅ test_get_cached_at PASSED")


def test_staleness_info():
    """测试数据陈旧状态检测"""
    f = push_svc._staleness_info

    # 空字符串 → None
    assert f('') is None

    # 无效日期格式 → None
    assert f('not-a-date') is None

    # 远早于现在 → data_offline (age > 300s)
    result = f('2020-01-01 00:00:00')
    assert result is not None
    assert result['level'] == 'data_offline'
    assert result['age_seconds'] > 300

    print("✅ test_staleness_info PASSED")


# ══════════════════════════════════════════════════════════════
# 推送函数测试（mock ECM + socketio）
# ══════════════════════════════════════════════════════════════


# ══════════════════════════════════════════════════════════════
# Mock 辅助 — 每次调用自动隔离
# ══════════════════════════════════════════════════════════════

_ORIGINAL_APP_MODULES: dict = {}  # 存储原始模块引用，测试后恢复


def _make_mock_app():
    """设置 mock 的 app.data 模块，让 push_service 的惰性导入能正常解析

    返回 (mock_ecm, mock_ws_bridge, cleanup_fn)
    调用 cleanup_fn() 恢复原始 sys.modules。
    """
    global _ORIGINAL_APP_MODULES

    # 保存原始 app 模块
    _ORIGINAL_APP_MODULES = {}
    for k in list(sys.modules.keys()):
        if k.startswith('app'):
            _ORIGINAL_APP_MODULES[k] = sys.modules[k]

    mock_ecm_mod = MagicMock()
    mock_ecm = MagicMock()
    mock_ecm_mod.get_ecm_instance.return_value = mock_ecm

    mock_ws_bridge = MagicMock()

    mock_data_mod = MagicMock()
    mock_data_mod.enhanced_cache_manager = mock_ecm_mod
    mock_data_mod.ws_bridge = MagicMock()
    mock_data_mod.ws_bridge.ws_bridge = mock_ws_bridge

    mock_app = MagicMock()
    mock_app.data = mock_data_mod

    sys.modules['app'] = mock_app
    sys.modules['app.data'] = mock_data_mod
    sys.modules['app.data.enhanced_cache_manager'] = mock_ecm_mod
    sys.modules['app.data.ws_bridge'] = mock_data_mod.ws_bridge

    def cleanup():
        """恢复原始 app 模块"""
        for k in list(sys.modules.keys()):
            if k.startswith('app'):
                if k in _ORIGINAL_APP_MODULES:
                    sys.modules[k] = _ORIGINAL_APP_MODULES[k]
                else:
                    del sys.modules[k]

    return mock_ecm, mock_ws_bridge, cleanup


def _make_snapshot(ts_code, price, prev_close, name='测试'):
    """生成测试用快照行"""
    return {
        'ts_code': ts_code,
        'name': name,
        'price': price,
        'prev_close': prev_close,
        'open': price * 0.99,
        'high': price * 1.01,
        'low': price * 0.98,
        'volume': 1000000,
        'amount': 10000000.0,
        'cached_at': '2026-07-10 14:30:00',
    }


def test_push_market_summary_counts():
    """测试市场概况的涨跌计数逻辑"""
    mock_sio = MagicMock()
    mock_ecm, _, cleanup = _make_mock_app()

    with patch.object(push_svc, '_get_socketio', return_value=mock_sio):
        mock_ecm.get_all_market_snapshots.return_value = [
            _make_snapshot('000001.SZ', 10.5, 10.0),   # +5%
            _make_snapshot('000002.SZ', 20.0, 19.0),   # +5.26%
            _make_snapshot('000003.SZ', 30.0, 29.0),   # +3.45%
            _make_snapshot('000004.SZ', 9.5, 10.0),    # -5%
            _make_snapshot('000005.SZ', 18.0, 20.0),   # -10%
            _make_snapshot('000006.SZ', 10.0, 10.0),   # 0%
        ]

        push_svc.push_market_summary()

        mock_sio.emit.assert_called()
        call_args = mock_sio.emit.call_args
        event, data = call_args[0][0], call_args[0][1]
        assert event == 'market:summary', f"事件名应为 market:summary, 实为 {event}"
        assert data['total'] == 6
        assert data['advancing'] == 3
        assert data['declining'] == 2
        assert data['unchanged'] == 1
        assert data['cached_at'] == '2026-07-10 14:30:00'

    cleanup()
    print("✅ test_push_market_summary_counts PASSED")


def test_push_top_stocks_ordering():
    """测试涨幅榜/跌幅榜 Top10 排序"""
    mock_sio = MagicMock()
    mock_ecm, _, cleanup = _make_mock_app()

    with patch.object(push_svc, '_get_socketio', return_value=mock_sio):
        mock_ecm.get_all_market_snapshots.return_value = [
            _make_snapshot(f'000{i:03d}.SZ', 10.0 + i * 0.5, 10.0)
            for i in range(20)
        ]

        push_svc.push_top_stocks()

        mock_sio.emit.assert_called()
        call_args = mock_sio.emit.call_args
        assert call_args[0][0] == 'market:top_stocks'
        data = call_args[0][1]
        assert len(data['gainers']) == 10
        assert len(data['losers']) == 10
        gainer_pcts = [g['change_pct'] for g in data['gainers']]
        loser_pcts = [l['change_pct'] for l in data['losers']]
        assert gainer_pcts == sorted(gainer_pcts, reverse=True), "涨幅榜应降序排列"
        assert loser_pcts == sorted(loser_pcts), "跌幅榜应升序排列"

    print("✅ test_push_top_stocks_ordering PASSED")
    cleanup()

def test_push_market_summary_empty():
    """测试空快照不抛异常"""
    mock_sio = MagicMock()
    mock_ecm, _, cleanup = _make_mock_app()

    with patch.object(push_svc, '_get_socketio', return_value=mock_sio):
        mock_ecm.get_all_market_snapshots.return_value = []

        push_svc.push_market_summary()

        mock_sio.emit.assert_called()
        data = mock_sio.emit.call_args[0][1]
        assert data['total'] == 0
        assert data['advancing'] == 0
        assert data['declining'] == 0
        assert data['unchanged'] == 0

    print("✅ test_push_market_summary_empty PASSED")
    cleanup()


def test_push_top_stocks_empty():
    """测试空快照的涨跌幅榜"""
    mock_sio = MagicMock()
    mock_ecm, _, cleanup = _make_mock_app()

    with patch.object(push_svc, '_get_socketio', return_value=mock_sio):
        mock_ecm.get_all_market_snapshots.return_value = []

        push_svc.push_top_stocks()

        mock_sio.emit.assert_called()
        data = mock_sio.emit.call_args[0][1]
        assert data['gainers'] == []
        assert data['losers'] == []

    print("✅ test_push_top_stocks_empty PASSED")
    cleanup()


def test_push_watchlist_quotes_filter():
    """测试自选股行情按代码过滤"""
    mock_sio = MagicMock()
    mock_ecm, mock_ws, cleanup = _make_mock_app()

    with patch.object(push_svc, '_get_socketio', return_value=mock_sio):
        mock_ws.get_watchlist_codes.return_value = ['000001.SZ', '000002.SZ']
        mock_ecm.get_all_market_snapshots.return_value = [
            _make_snapshot('000001.SZ', 10.5, 10.0),
            _make_snapshot('000002.SZ', 20.0, 19.0),
        ]

        push_svc.push_watchlist_quotes()

        mock_ecm.get_all_market_snapshots.assert_called_with(codes=['000001.SZ', '000002.SZ'])

        mock_sio.emit.assert_called()
        call_args = mock_sio.emit.call_args
        assert call_args[0][0] == 'stock:quotes'
        data = call_args[0][1]
        assert len(data['quotes']) == 2
        assert data['quotes'][0]['ts_code'] == '000001.SZ'
        assert call_args[1].get('room') == 'watchlist'

    print("✅ test_push_watchlist_quotes_filter PASSED")
    cleanup()


def test_push_watchlist_quotes_empty():
    """测试无自选股时跳过推送"""
    mock_sio = MagicMock()
    _, mock_ws, cleanup = _make_mock_app()

    with patch.object(push_svc, '_get_socketio', return_value=mock_sio):
        mock_ws.get_watchlist_codes.return_value = []

        push_svc.push_watchlist_quotes()

        mock_sio.emit.assert_not_called()

    print("✅ test_push_watchlist_quotes_empty PASSED")
    cleanup()


def test_push_market_summary_socketio_none():
    """测试 socketio 不可用时静默返回"""
    with patch.object(push_svc, '_get_socketio', return_value=None):
        push_svc.push_market_summary()
    print("✅ test_push_market_summary_socketio_none PASSED")


def test_compute_change_mixed():
    """测试涨跌各异的快照"""
    mock_sio = MagicMock()
    mock_ecm, _, cleanup = _make_mock_app()

    with patch.object(push_svc, '_get_socketio', return_value=mock_sio):
        mock_ecm.get_all_market_snapshots.return_value = [
            _make_snapshot('000001.SZ', 10.0, 10.0),    # 0%
            _make_snapshot('000002.SZ', 11.0, 10.0),    # +10%
            _make_snapshot('000003.SZ', 9.0, 10.0),     # -10%
            _make_snapshot('000004.SZ', 10.0, 10.0),    # 0%
        ]

        push_svc.push_market_summary()

        data = mock_sio.emit.call_args[0][1]
        assert data['total'] == 4
        assert data['advancing'] == 1
        assert data['declining'] == 1
        assert data['unchanged'] == 2

    print("✅ test_compute_change_mixed PASSED")
    cleanup()


# ══════════════════════════════════════════════════════════════
# 测试入口
# ══════════════════════════════════════════════════════════════


def run_all():
    print("=" * 50)
    print("📊 push_service 单元测试（迭代2）")
    print("=" * 50)
    print()

    # 保存原始 sys.modules，避免污染后续测试
    _saved_modules = {
        k: v for k, v in sys.modules.items()
        if k.startswith('app')
    }

    tests = [
        test_compute_change_pct,
        test_get_cached_at,
        test_staleness_info,
        test_push_market_summary_counts,
        test_push_top_stocks_ordering,
        test_push_market_summary_empty,
        test_push_top_stocks_empty,
        test_push_watchlist_quotes_filter,
        test_push_watchlist_quotes_empty,
        test_push_market_summary_socketio_none,
        test_compute_change_mixed,
    ]

    passed = 0
    failed = 0

    for test in tests:
        try:
            test()
            passed += 1
        except Exception as e:
            print(f"❌ {test.__name__} FAILED: {e}")
            import traceback
            traceback.print_exc()
            failed += 1

    # 恢复原始模块，避免污染后续测试
    for k in list(sys.modules.keys()):
        if k.startswith('app'):
            if k in _saved_modules:
                sys.modules[k] = _saved_modules[k]
            else:
                del sys.modules[k]

    print()
    print("=" * 50)
    print(f"📋 测试结果: {passed}/{len(tests)} 通过, {failed}/{len(tests)} 失败")
    print("=" * 50)

    return failed == 0


if __name__ == '__main__':
    success = run_all()
    sys.exit(0 if success else 1)
