"""
实时快照数据库单元测试（迭代1：实时快照入库）
测试 EnhancedCacheManager 的 market_snapshot.db 读写功能
"""
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))




def _make_test_records(count=3):
    """生成测试用的快照记录列表"""
    records = []
    base_stocks = [
        ('000001.SZ', '000001', '平安银行'),
        ('000002.SZ', '000002', '万科A'),
        ('600000.SH', '600000', '浦发银行'),
    ]
    for i in range(min(count, len(base_stocks))):
        ts_code, code, name = base_stocks[i]
        records.append({
            'ts_code': ts_code,
            'code': code,
            'name': name,
            'price': 10.0 + i,
            'open': 9.9 + i,
            'high': 10.2 + i,
            'low': 9.8 + i,
            'prev_close': 9.95 + i,
            'volume': 1000000 * (i + 1),
            'amount': 10000000.0 * (i + 1),
            'bid1': 10.01 + i, 'ask1': 10.02 + i,
            'bid_vol1': 10000 * (i + 1), 'ask_vol1': 8000 * (i + 1),
            'bid2': 10.00 + i, 'ask2': 10.03 + i,
            'bid_vol2': 8000 * (i + 1), 'ask_vol2': 6000 * (i + 1),
            'bid3': 9.99 + i, 'ask3': 10.04 + i,
            'bid_vol3': 5000 * (i + 1), 'ask_vol3': 4000 * (i + 1),
            'bid4': 9.98 + i, 'ask4': 10.05 + i,
            'bid_vol4': 3000 * (i + 1), 'ask_vol4': 2000 * (i + 1),
            'bid5': 9.97 + i, 'ask5': 10.06 + i,
            'bid_vol5': 1000 * (i + 1), 'ask_vol5': 500 * (i + 1),
        })
    return records


def test_snapshot_write_and_read_single():
    """测试写入快照 + 查询单只股票"""
    from app.data.enhanced_cache_manager import get_ecm_instance
    ecm = get_ecm_instance()

    records = _make_test_records(1)
    ecm.cache_market_snapshot_data(records)

    snap = ecm.get_market_snapshot('000001.SZ')
    assert snap, "应能查询到写入的快照"
    assert snap['ts_code'] == '000001.SZ'
    assert float(snap['price']) == 10.0
    assert float(snap['bid1']) == 10.01
    assert snap['ask_vol1'] == 8000
    assert float(snap['bid2']) == 10.00
    assert 'cached_at' in snap, "应包含 cached_at 时间戳"
    print("✅ test_snapshot_write_and_read_single PASSED")


def test_snapshot_missing_stock():
    """测试查询不存在的股票返回空字典"""
    from app.data.enhanced_cache_manager import get_ecm_instance
    ecm = get_ecm_instance()

    snap = ecm.get_market_snapshot('999999.ZZ')
    assert snap == {}, "不存在的股票应返回空字典"
    print("✅ test_snapshot_missing_stock PASSED")


def test_snapshot_batch_write_and_read_all():
    """测试批量写入 + 全量查询"""
    from app.data.enhanced_cache_manager import get_ecm_instance
    ecm = get_ecm_instance()

    records = _make_test_records(3)
    ecm.cache_market_snapshot_data(records)

    all_snaps = ecm.get_all_market_snapshots()
    assert len(all_snaps) >= 3, f"应至少包含 3 条快照, 实际 {len(all_snaps)}"

    ts_codes = [s['ts_code'] for s in all_snaps]
    assert '000001.SZ' in ts_codes
    assert '000002.SZ' in ts_codes
    assert '600000.SH' in ts_codes

    # 验证数据完整性（仅检查我们写入的测试记录）
    test_codes = ['000001.SZ', '000002.SZ', '600000.SH']
    for s in all_snaps:
        if s['ts_code'] in test_codes:
            assert float(s['price']) > 0
            assert float(s['bid1']) > 0
            assert float(s['ask1']) > 0
    print("✅ test_snapshot_batch_write_and_read_all PASSED")


def test_snapshot_read_filtered():
    """测试按指定股票代码列表查询"""
    from app.data.enhanced_cache_manager import get_ecm_instance
    ecm = get_ecm_instance()

    records = _make_test_records(3)
    ecm.cache_market_snapshot_data(records)

    filtered = ecm.get_all_market_snapshots(codes=['000001.SZ', '600000.SH'])
    assert len(filtered) == 2, f"应返回 2 条, 实际 {len(filtered)}"

    codes_found = [s['ts_code'] for s in filtered]
    assert '000001.SZ' in codes_found
    assert '600000.SH' in codes_found
    assert '000002.SZ' not in codes_found
    print("✅ test_snapshot_read_filtered PASSED")


def test_snapshot_insert_or_replace():
    """测试 INSERT OR REPLACE：写入同一条 ts_code 应覆盖旧数据"""
    from app.data.enhanced_cache_manager import get_ecm_instance
    ecm = get_ecm_instance()

    records = _make_test_records(1)
    # 第一次写入
    ecm.cache_market_snapshot_data(records)

    # 修改价格后再次写入同一只股票
    updated = records.copy()
    updated[0] = dict(records[0], price=99.99)
    ecm.cache_market_snapshot_data(updated)

    snap = ecm.get_market_snapshot('000001.SZ')
    assert snap, "覆盖后应能查到"
    assert float(snap['price']) == 99.99, "price 应被更新为 99.99"
    print("✅ test_snapshot_insert_or_replace PASSED")


def test_snapshot_empty_records():
    """测试写入空列表不报错"""
    from app.data.enhanced_cache_manager import get_ecm_instance
    ecm = get_ecm_instance()

    # 应静默返回，不抛异常
    ecm.cache_market_snapshot_data([])
    ecm.cache_market_snapshot_data(None)

    print("✅ test_snapshot_empty_records PASSED")


def run_all():
    print("=" * 50)
    print("📊 实时快照数据库单元测试（迭代1）")
    print("=" * 50)
    print()

    tests = [
        test_snapshot_write_and_read_single,
        test_snapshot_missing_stock,
        test_snapshot_batch_write_and_read_all,
        test_snapshot_read_filtered,
        test_snapshot_insert_or_replace,
        test_snapshot_empty_records,
    ]

    passed = 0
    failed = 0

    for test in tests:
        try:
            test()
            passed += 1
        except Exception as e:
            print(f"❌ {test.__name__} FAILED: {str(e)}")
            import traceback
            traceback.print_exc()
            failed += 1

    print()
    print("=" * 50)
    print(f"📋 测试结果: {passed}/{len(tests)} 通过, {failed}/{len(tests)} 失败")
    print("=" * 50)

    return failed == 0


if __name__ == '__main__':
    success = run_all()
    sys.exit(0 if success else 1)
