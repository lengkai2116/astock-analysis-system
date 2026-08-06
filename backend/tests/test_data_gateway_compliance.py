"""全局数据体系合规整改回归测试（2026-08-06）

覆盖整改点：
  1. DataManager 新增网关方法：get_snapshot_max_date / get_previous_trade_date /
     get_tags_by_date（替代调用层直连 ECM conn）
  2. L4 诊断路由改用 dm.cache.get_tags（不再直连 ecm.conn）
  3. 防复发静态守卫：routes/ 与 opportunity_atlas 计算引擎禁止 conn.execute 直连模式
"""
import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
for k in ['HTTP_PROXY', 'HTTPS_PROXY', 'ALL_PROXY']:
    os.environ.pop(k, None)

import re


# ══════════════════════════════════════════════════════════
# 1. DataManager 网关方法（整改①②③的基础）
# ══════════════════════════════════════════════════════════

def test_dm_gateway_methods_exist():
    """DataManager 必须提供 3 个新网关方法（替代调用层直连）"""
    from app.data import DataManager
    dm = DataManager()
    assert hasattr(dm, 'get_snapshot_max_date'), "缺少 get_snapshot_max_date 网关"
    assert hasattr(dm, 'get_previous_trade_date'), "缺少 get_previous_trade_date 网关"
    assert hasattr(dm, 'get_tags_by_date'), "缺少 get_tags_by_date 网关"


def test_dm_get_snapshot_max_date_returns_value():
    """get_snapshot_max_date 应返回 treemap_snapshot 最新日期（非 None）"""
    from app.data import DataManager
    dm = DataManager()
    d = dm.get_snapshot_max_date()
    assert d is not None, "快照日期不应为 None（表有数据）"


def test_dm_get_previous_trade_date_returns_value():
    """get_previous_trade_date 应返回上一交易日"""
    from app.data import DataManager
    dm = DataManager()
    d = dm.get_previous_trade_date()
    assert d is not None, "上一交易日不应为 None"


def test_dm_get_tags_by_date_returns_dict():
    """get_tags_by_date 应返回指定日期的标签 dict"""
    from app.data import DataManager
    dm = DataManager()
    # 用最近快照日期内的股票查询（600519.SH 有标签）
    tags = dm.get_tags_by_date('600519.SH')
    assert isinstance(tags, dict), "get_tags_by_date 应返回 dict"


# ══════════════════════════════════════════════════════════
# 2. L4 诊断路由改用网关（整改①）
# ══════════════════════════════════════════════════════════

def test_l4_diagnose_route_no_conn_direct():
    """L4 诊断路由不得直连 ecm.conn（红线5）——应改用 dm.cache.get_tags"""
    src = open(os.path.join(os.path.dirname(__file__), '..', 'app', 'routes',
                            'opportunity_atlas.py'), encoding='utf-8').read()
    # 排除注释行后，不应再有可执行的 ecm.conn.execute 直连
    code_lines = [l for l in src.splitlines() if not l.strip().startswith('#')]
    assert not any('ecm.conn.execute' in l for l in code_lines), \
        "L4 诊断路由禁止直连 ecm.conn（应走 DataManager 网关）"
    assert 'dm.cache.get_tags(ts_code)' in src, "L4 诊断路由应使用 dm.cache.get_tags 网关方法"


# ══════════════════════════════════════════════════════════
# 3. cross_validate 直连改网关（整改②）
# ══════════════════════════════════════════════════════════

def test_cross_validate_no_conn_direct():
    """cross_validate.py 不得直连 cache.conn（红线5）——应走 DataManager 网关"""
    src = open(os.path.join(os.path.dirname(__file__), '..', 'app', 'opportunity_atlas',
                            'cross_validate.py'), encoding='utf-8').read()
    assert 'cache.conn.execute' not in src, \
        "cross_validate.py 禁止 cache.conn.execute 直连（应走 DataManager 网关方法）"
    assert 'self._get_dm().get_previous_trade_date' in src or \
        'dm.get_previous_trade_date' in src, "应调用 DataManager.get_previous_trade_date 网关"
    assert 'get_tags_by_date' in src, "应调用 DataManager.get_tags_by_date 网关"


# ══════════════════════════════════════════════════════════
# 4. treemap 路由 MAX(snapshot_date) 改网关（整改③）
# ══════════════════════════════════════════════════════════

def test_treemap_route_no_conn_direct():
    """treemap 路由不得直连 get_ecm().conn（红线5）——应走 DataManager 网关"""
    src = open(os.path.join(os.path.dirname(__file__), '..', 'app', 'routes',
                            'opportunity_atlas.py'), encoding='utf-8').read()
    # 全文件不应再有 get_ecm().conn.execute / ecm.conn.execute
    assert 'get_ecm().conn.execute' not in src, "treemap 路由禁止直连 get_ecm().conn"
    assert 'get_snapshot_max_date' in src, "treemap 路由应使用 get_snapshot_max_date 网关"


# ══════════════════════════════════════════════════════════
# 5. 防复发静态守卫（红线5 全目录）
# ══════════════════════════════════════════════════════════

def test_routes_no_direct_conn_access():
    """routes/ 目录禁止出现 .conn.execute 直连（红线5 防复发守卫）

    例外：health.py 的 data_freshness 检查 ECM 状态表（系统诊断，非业务读取）。
    """
    routes_dir = os.path.join(os.path.dirname(__file__), '..', 'app', 'routes')
    offenders = []
    for fname in sorted(os.listdir(routes_dir)):
        if not fname.endswith('.py') or fname == '__init__.py':
            continue
        path = os.path.join(routes_dir, fname)
        with open(path, encoding='utf-8') as f:
            for i, line in enumerate(f, 1):
                stripped = line.strip()
                # 排除注释行（整改说明里含历史违规字样）、PRAGMA 与系统诊断
                if stripped.startswith('#'):
                    continue
                if '.conn.execute' in line and 'conn.execute("PRAGMA' not in line:
                    offenders.append(f'{fname}:{i}: {stripped[:60]}')
    # health.py 的 data_freshness 属系统诊断例外（读取缓存状态），允许保留
    allowed = [o for o in offenders if 'health.py' in o]
    real = [o for o in offenders if o not in allowed]
    assert not real, f"routes/ 存在直连违规: {real}"
