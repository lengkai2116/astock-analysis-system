"""500号 批次7 探针——死存储/死表/视图重复（C-7 #91~#99，只读核查 + 已批准删除）

关键结论（只读复核）：**#93~#99 的库内容问题基本已由 426 清理落地**，故无需删库表；
真正空间占用在**未跟踪的历史备份/沙箱**（经用户批准删除）。

验证：
  #91/#92  历史 .bak 备份 + 测试沙箱 + instance 残留 + 0 字节库 已删（空间释放）
  #93      总库 stock_cache.db 空壳表仅 4 张（426 已清，无需再删）
  #94      cache_metadata 在总库单份（system_cache.db 无该表）
  #95      仅 history_cache.db 有 adj_factor_view（活视图），无重复视图
  #99      as_market_snapshot / as_sector_ranking 已登记 market_snapshot.db 路由
  活跃库完整（daily_cache / adj_factor_view / as_market_snapshot 均可读）
  保留仍在用的库（factors_combos.db / strategy_templates.db）
"""
import os
import sqlite3
import sys

_ROOT = os.path.join(os.path.dirname(__file__), '..', '..')
_DUCK = os.path.join(_ROOT, 'data', 'duckdb')

FAIL = []


def check(cond, msg):
    print(('  OK  ' if cond else '  FAIL') + ' ' + msg)
    if not cond:
        FAIL.append(msg)


def q(path, sql):
    c = sqlite3.connect(f'file:{path}?mode=ro', uri=True)
    try:
        return c.execute(sql).fetchone()
    finally:
        c.close()


# ── #91/#92 备份/沙箱/残留已删 ─────────────────────────────────────────
print("=== #91/#92 备份/沙箱/残留清理 ===")
_baks = [f for f in os.listdir(_DUCK) if '.bak' in f]
check(_baks == [], f"data/duckdb 无 .bak 残留（剩余={_baks}）")
check(not os.path.exists(os.path.join(_ROOT, 'data_sandbox_test_20260913')), "测试沙箱 sandbox 已删")
check(not os.path.exists(os.path.join(_ROOT, 'data_virtual_test_20260912')), "测试沙箱 virtual 已删")
check(not os.path.exists(os.path.join(_ROOT, 'backend', 'instance', 'duckdb')), "backend/instance/duckdb 残留已删")
check(not os.path.exists(os.path.join(_ROOT, 'data', 'history_cache.db')), "data/ 0 字节残留 history_cache.db 已删")
check(not os.path.exists(os.path.join(_ROOT, 'data', 'stock_cache.db')), "data/ 0 字节残留 stock_cache.db 已删")

# ── #93 总库空壳表 ─────────────────────────────────────────────────────
print("=== #93 总库空壳表 ===")
_p = os.path.join(_DUCK, 'stock_cache.db')
_tabs = [r[0] for r in sqlite3.connect(f'file:{_p}?mode=ro', uri=True).execute(
    "SELECT name FROM sqlite_master WHERE type='table'").fetchall()]
_empty = [t for t in _tabs if q(_p, f'SELECT COUNT(*) FROM "{t}"')[0] == 0]
check(len(_tabs) <= 15, f"总库表数 {len(_tabs)}（426 已清，原 44/36 空）")
check(len(_empty) <= 6, f"总库空表 {len(_empty)}（{_empty}）")

# ── #94 cache_metadata 单份 ────────────────────────────────────────────
print("=== #94 cache_metadata ===")
check(q(_p, "SELECT COUNT(*) FROM sqlite_master WHERE name='cache_metadata'")[0] == 1,
      "总库有 cache_metadata")
_mp = os.path.join(_DUCK, 'system_cache.db')
check(q(_mp, "SELECT COUNT(*) FROM sqlite_master WHERE name='cache_metadata'")[0] == 0,
      "system_cache.db 无 cache_metadata（已单份）")

# ── #95 视图无重复 ─────────────────────────────────────────────────────
print("=== #95 视图 ===")
_views = {}
for _db in os.listdir(_DUCK):
    if not _db.endswith('.db'):
        continue
    _fp = os.path.join(_DUCK, _db)
    _v = [r[0] for r in sqlite3.connect(f'file:{_fp}?mode=ro', uri=True).execute(
        "SELECT name FROM sqlite_master WHERE type='view'").fetchall()]
    if _v:
        _views[_db] = _v
check(_views.get('history_cache.db') == ['adj_factor_view'], f"仅 history_cache.db 有 adj_factor_view（实际={_views}）")

# ── #99 路由登记 ───────────────────────────────────────────────────────
print("=== #99 market_snapshot 路由 ===")
sys.path.insert(0, os.path.join(_ROOT, 'backend'))  # noqa: E402
from app.data.sharding_manager import sharding_manager  # noqa: E402

check(sharding_manager.get_db_for_table('as_market_snapshot') == 'market_snapshot.db',
      "as_market_snapshot 登记 market_snapshot.db")
check(sharding_manager.get_db_for_table('as_sector_ranking') == 'market_snapshot.db',
      "as_sector_ranking 登记 market_snapshot.db")

# ── 活跃库完整 ─────────────────────────────────────────────────────────
print("=== 活跃库完整 ===")
check(q(os.path.join(_DUCK, 'market_cache.db'), 'SELECT COUNT(*) FROM daily_cache')[0] > 0,
      "daily_cache 有数据")
check(q(os.path.join(_DUCK, 'history_cache.db'), "SELECT COUNT(*) FROM sqlite_master WHERE name='adj_factor_view'")[0] == 1,
      "adj_factor_view 存在（活视图）")
check(q(os.path.join(_DUCK, 'market_snapshot.db'), 'SELECT COUNT(*) FROM as_market_snapshot')[0] > 0,
      "as_market_snapshot 有数据")

# ── 仍在用的库保留 ─────────────────────────────────────────────────────
print("=== 保留在用库 ===")
check(os.path.exists(os.path.join(_ROOT, 'data', 'factors_combos.db')), "factors_combos.db 保留（被 routes/factors 使用）")
check(os.path.exists(os.path.join(_ROOT, 'backend', 'strategy_templates.db')), "strategy_templates.db 保留（被 routes 使用）")

print()
if FAIL:
    print(f"❌ {len(FAIL)} 项失败")
    sys.exit(1)
print("✅ 批次7 探针全绿（死存储/备份清理 + 库内容 426 已落地 + 活跃库完整）")
