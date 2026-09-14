"""沙盒双切隔离 conftest（开发期数据隔离红线，2026-09-13）

仅在设置了环境变量 `TEST_DATA_DIR` 时启用：把 `DATA_DIR`（ECM 总库）与
分库路由 `sharding_manager` 一并切到该沙盒目录（duckdb 子目录），实现双切，
避免 `make test` 写污染开发基准数据目录（data/duckdb）。

用法（在沙盒克隆上跑完整回归）：
    TEST_DATA_DIR=/abs/path/to/sandbox make test

未设 `TEST_DATA_DIR` → 本模块不干预（模块级空实现），默认行为不变。
"""
import os
import sys

_test_data_dir = os.environ.get('TEST_DATA_DIR')

if _test_data_dir:
    _test_data_dir = os.path.abspath(_test_data_dir)

    # 1) ECM 总库（stock_cache.db / app.db / 各分库读）指向沙盒
    os.environ['DATA_DIR'] = _test_data_dir

    # 2) 分库写路由单例整体切到沙盒（必须与 DATA_DIR 一起，否则写库走默认 data/duckdb）
    try:
        from app.data.sharding_manager import init_sharding
        init_sharding(_test_data_dir)
    except Exception as _e:  # pragma: no cover - 采集环境差异
        print(f'[conftest] sharding 双切失败: {_e}', file=sys.stderr)

    print(f'[conftest] 沙盒双切隔离生效: DATA_DIR={_test_data_dir}', file=sys.stderr)
