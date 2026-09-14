"""426号方案阶段三：调度闭环与 P1 功能修复测试

验证 §10 阶段三检验标准（不依赖真实生产数据库，临时库/故障注入）：
- 3.2 P1-2：三表（market_stats_cache/sector_heat_cache/pattern_score_cache）
      已登记 compute_cache.db 路由；ECM 写路径走 _exec_shard（分库），
      不再落总库空壳；pattern_score 不再硬编码 compute_conn
- 3.3 P1-5：注册表零重名（len(set)==len）；register 重名报错拒绝覆盖；
      _load_builtin_factors 按 sorted 字典序加载
- 3.4 P1-6：_init_tables 源码不含盲 ALTER（duplicate column 噪声源已删除）
- 3.1 P0-4：pipeline_status 时间存本地（localtime），超时比较同步本地化；
      _drive_pipeline RAW 提交前打触发条件日志
- 3.5 P1-3：_precompute_raw_features 接受 target_date 参数（回补口径）
"""
import inspect
import os
import sqlite3
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.data.sharding_manager import ShardingManager, sharding_manager
from app.factors import get_factor_registry

# ── 3.2 P1-2：三表路由登记 ──────────────────────────────────

def test_three_tables_registered_to_compute():
    """426号 3.2 检验：_table_to_db 命中三表 → compute_cache.db"""
    for t in ('market_stats_cache', 'sector_heat_cache', 'pattern_score_cache'):
        assert sharding_manager.get_db_for_table(t) == 'compute_cache.db', t
        assert sharding_manager.is_registered(t), t


def test_ecm_write_paths_use_shard(tmp_path):
    """ECM 三表写路径改走 _exec_shard（不再 _execute 落总库 / compute_conn 硬编码）"""
    from app.data.enhanced_cache_manager import EnhancedCacheManager
    ecm = EnhancedCacheManager.__new__(EnhancedCacheManager)
    ecm._write_lock = __import__('threading').RLock()
    executed = []

    def fake_exec_shard(table, sql, params=None):
        executed.append((table, sql))

    ecm._exec_shard = fake_exec_shard
    ecm.compute_conn = None  # 若仍走 compute_conn 硬编码会 AttributeError

    ecm.cache_market_stats({'computed_at': '2026-09-11', 'ma20_ratio': 0.5})
    assert executed and executed[0][0] == 'market_stats_cache'
    assert 'INSERT OR REPLACE INTO market_stats_cache' in executed[0][1]

    executed.clear()
    ecm.cache_sector_heat({'银行': {'heat_level': 'hot', 'strength': 1.0,
                                   'rank': 1, 'stock_count': 5}}, '2026-09-11')
    assert executed and executed[0][0] == 'sector_heat_cache'
    assert executed[0][1].startswith('DELETE FROM sector_heat_cache')
    assert executed[1][0] == 'sector_heat_cache'
    assert 'INSERT INTO sector_heat_cache' in executed[1][1]

    executed.clear()
    ecm.cache_pattern_score('000001.SZ', '2026-09-11', 7.5, {'bull_count': 3})
    assert executed and executed[0][0] == 'pattern_score_cache'
    assert 'INSERT OR REPLACE INTO pattern_score_cache' in executed[0][1]


# ── 3.3 P1-5：因子名去重 ─────────────────────────────────────

def test_factor_registry_no_duplicate_names():
    """426号 3.3 检验：加载后 len(set(names)) == len(names)（13 项重名已唯一化）"""
    reg = get_factor_registry()
    names = reg.list_factors()
    assert len(names) == len(set(names))
    # 裸名解析稳定：KDJ/MA/BOLL/OBV/GTJA 保留在专业模块
    assert reg.get_factor_class('KDJ_K').__module__.endswith('momentum')
    assert reg.get_factor_class('MACD_DIF').__module__.endswith('momentum')
    assert reg.get_factor_class('BOLL_UPPER').__module__.endswith('volatility')
    assert reg.get_factor_class('OBV').__module__.endswith('volume')
    assert reg.get_factor_class('GTJA001').__module__.endswith('gtja191')
    # 副定义已加来源前缀
    assert reg.get_factor_class('ASTOCK_KDJ_K').__module__.endswith('a_stock')
    assert reg.get_factor_class('ASTOCK_MACD_DIF').__module__.endswith('a_stock')
    assert reg.get_factor_class('ASTOCK_BOLL_UPPER').__module__.endswith('a_stock')
    assert reg.get_factor_class('ASTOCK_OBV').__module__.endswith('a_stock')


def test_register_duplicate_raises():
    """426号 3.3：register 重名改报错拒绝覆盖（原 warning 后覆盖）"""
    from app.factors.base import BaseFactor
    from app.factors.registry import FactorRegistry

    class F1(BaseFactor):
        name = 'DUP_426'
        category = 'test'
        source = 'test'

    class F2(BaseFactor):
        name = 'DUP_426'
        category = 'test'
        source = 'test'

    reg = FactorRegistry()
    reg.register(F1)
    try:
        reg.register(F2)
        assert False, '重名应抛 ValueError'
    except ValueError as e:
        assert '拒绝注册' in str(e)
    # 原定义保留（拒绝覆盖）
    assert reg.get_factor_class('DUP_426') is F1


def test_load_builtin_factors_sorted():
    """426号 3.3：_load_builtin_factors 按 sorted 字典序加载（消除 listdir 顺序漂移）"""
    from app.factors import registry as reg_mod
    src = inspect.getsource(reg_mod._load_builtin_factors)
    assert 'sorted(os.listdir(builtin_dir))' in src


# ── 3.4 P1-6：盲 ALTER 已删除 ───────────────────────────────

def test_init_tables_no_blind_alter():
    """426号 3.4 检验：_init_tables 无 7 条盲 ALTER（duplicate column 噪声源）"""
    from app.data.enhanced_cache_manager import EnhancedCacheManager
    src = inspect.getsource(EnhancedCacheManager._init_tables)
    assert 'ALTER TABLE indicator_ma ADD COLUMN' not in src
    assert 'ALTER TABLE indicator_other ADD COLUMN' not in src
    assert "for _col in ['ma120', 'ma250']" not in src


# ── 3.1 P0-4：管道时间本地化 + RAW 触发日志 ─────────────────

def test_pipeline_status_uses_localtime():
    """426号 3.1-④：mark_step_* 时间写本地（datetime('now','localtime')），
    不再用 UTC 的 CURRENT_TIMESTAMP；超时比较同步本地化"""
    from app.data.enhanced_cache_manager import EnhancedCacheManager
    src = inspect.getsource(EnhancedCacheManager.mark_step_done) + \
          inspect.getsource(EnhancedCacheManager.mark_step_failed) + \
          inspect.getsource(EnhancedCacheManager.mark_step_running)
    assert "started_at=datetime('now','localtime')" in src
    assert "completed_at=datetime('now','localtime')" in src
    assert "started_at < datetime('now','localtime', ?)" in src
    # 写/比较 SQL 不再出现 UTC 的 CURRENT_TIMESTAMP（docstring 提及属注释，不计）
    assert 'started_at=CURRENT_TIMESTAMP' not in src
    assert 'completed_at=CURRENT_TIMESTAMP' not in src


def test_drive_pipeline_timestamps_localtime():
    """data_daemon _drive_pipeline / _recover_stale_running 时间本地化"""
    import data_daemon as dd
    src = inspect.getsource(dd._drive_pipeline) + inspect.getsource(dd._recover_stale_running)
    assert "datetime('now','localtime')" in src
    assert 'completed_at=CURRENT_TIMESTAMP' not in src
    assert "started_at < datetime('now', ?)" not in src


def test_raw_trigger_logging_present():
    """426号 3.1-⑤：RAW 触发条件加日志（为何 pending：COL 待完成/无活跃代码/提交状态）"""
    import data_daemon as dd
    src = inspect.getsource(dd._drive_pipeline)
    assert 'RAW 等待采集完成' in src
    assert '无活跃股票代码' in src
    assert 'RAW 并行提交' in src


# ── 3.5 P1-3：pre_feat 回补口径 ─────────────────────────────

def test_precompute_raw_features_accepts_target_date():
    """426号 3.5：_precompute_raw_features 支持 target_date 参数（回补限定日期）"""
    import data_daemon as dd
    sig = inspect.signature(dd._precompute_raw_features)
    assert 'target_date' in sig.parameters
    src = inspect.getsource(dd._precompute_raw_features)
    assert "df['trade_date'].astype(str).str[:10] <= target_date" in src


def test_ma20_ratio_window_not_prefiltered():
    """426号 阶段三复核：ma20_ratio 窗口函数须在全历史计算后按当日过滤

    （原实现窗口内先 WHERE trade_date=? → 每只仅 1 行 → SMA_20=当日 close
    → close>SMA_20 恒 False → ma20_ratio 恒 0.0 假值；回归防复发）
    """
    import data_daemon as dd
    src = inspect.getsource(dd._precompute_market_stats)
    # 窗口子查询内部不得出现当日过滤
    seg = src[src.index('def _ma20_ratio'):src.index("_run('ma20_ratio'")]
    assert "FROM daily_cache\n                    WHERE trade_date = ?" not in seg
    # 外层按当日过滤必须存在
    assert "\n                WHERE trade_date = ?" in seg


# ── 路由一致性：get_all_db_names 含 compute 新表路由 ─────────

def test_compute_db_in_route_table():
    assert 'compute_cache.db' in sharding_manager.get_all_db_names()
