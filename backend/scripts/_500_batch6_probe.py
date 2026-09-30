"""500号 批次6 探针——死模块删除（Q1=B 收窄为 5 模块 + create_views 4 死函数）

验证：
  5 个死模块文件已删除（config_manager/migration/init_sharding/health_checker/data_inventory）
  5 个模块均不可 import（ModuleNotFoundError）
  create_views.py 保留 + create_adj_factor_view 仍可用（活代码，adj_factor_view 生产读取）
  create_views 4 个死函数已删除
  无残留引用（动态 import 扫描）
"""
import importlib
import inspect
import os
import sqlite3
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

FAIL = []


def check(cond, msg):
    print(('  OK  ' if cond else '  FAIL') + ' ' + msg)
    if not cond:
        FAIL.append(msg)


# ── 5 个死模块已删除 ────────────────────────────────────────────────────
print("=== 5 个死模块删除 ===")
_DEAD = ['config_manager', 'migration', 'init_sharding', 'health_checker', 'data_inventory']
for _m in _DEAD:
    _p = os.path.join(os.path.dirname(__file__), '..', 'app', 'data', f'{_m}.py')
    check(not os.path.exists(_p), f"{_m}.py 文件已删除")
    try:
        importlib.import_module(f'app.data.{_m}')
        check(False, f"app.data.{_m} 应不可 import")
    except ModuleNotFoundError:
        check(True, f"app.data.{_m} 不可 import")

# ── create_views 保留 + 活函数可用 ──────────────────────────────────────
print("=== create_views 保留（活代码）===")
try:
    from app.data.create_views import create_adj_factor_view
    check(callable(create_adj_factor_view), "create_adj_factor_view 保留可用")
except Exception as e:
    check(False, f"create_adj_factor_view 导入失败: {e}")

# 端到端：临时库建年表 → 建视图 → 校验 UNION 覆盖
import tempfile  # noqa: E402

_tmp = tempfile.mkdtemp()
_dbdir = os.path.join(_tmp, 'duckdb')
os.makedirs(_dbdir, exist_ok=True)
_conn = sqlite3.connect(os.path.join(_dbdir, 'history_cache.db'))
for _y in ('2001', '2025', '2026'):
    _conn.execute(f"CREATE TABLE adj_factor_cache_{_y} (ts_code TEXT, trade_date TEXT, adj_factor REAL, cached_at TIMESTAMP)")
_conn.commit()
_conn.close()
check(create_adj_factor_view(_tmp) is True, "create_adj_factor_view 端到端成功")
_conn = sqlite3.connect(os.path.join(_dbdir, 'history_cache.db'))
_sql = _conn.execute("SELECT sql FROM sqlite_master WHERE type='view' AND name='adj_factor_view'").fetchone()[0]
_conn.close()
check('adj_factor_cache_2026' in _sql and _sql.count('UNION ALL') == 2, "adj_factor_view 覆盖 3 张年表")

# 4 个死函数已删
import app.data.create_views as cv  # noqa: E402

for _dead_fn in ['create_daily_data_view', 'create_financial_data_view', 'create_all_views', 'drop_all_views']:
    check(not hasattr(cv, _dead_fn), f"死函数 {_dead_fn} 已删除")

# ── 活消费者未被破坏（ECM 读 adj_factor_view） ──────────────────────────
print("=== 活消费者（ECM）保留 ===")
from app.data.enhanced_cache_manager import EnhancedCacheManager  # noqa: E402

_src = inspect.getsource(EnhancedCacheManager.get_cached_adj_factor)
check('adj_factor_view' in _src, "ECM.get_cached_adj_factor 仍读 adj_factor_view（活链）")

# ── 无残留引用 ──────────────────────────────────────────────────────────
print("=== 无残留引用 ===")
_backend = os.path.join(os.path.dirname(__file__), '..')
_hits = []
for _root, _dirs, _files in os.walk(_backend):
    _dirs[:] = [d for d in _dirs if d not in ('__pycache__', '.venv')]
    for _f in _files:
        if not _f.endswith('.py'):
            continue
        _path = os.path.join(_root, _f)
        if _f in ('_500_batch6_probe.py',):
            continue
        try:
            with open(_path, encoding='utf-8') as _fh:
                _txt = _fh.read()
        except Exception:
            continue
        for _m in _DEAD:
            if f'app.data.{_m}' in _txt or f'from app.data import {_m}' in _txt:
                _hits.append((_path, _m))
check(_hits == [], f"无 app.data.<死模块> 残留引用（命中={_hits}）")

print()
if FAIL:
    print(f"❌ {len(FAIL)} 项失败")
    sys.exit(1)
print("✅ 批次6 探针全绿（5 模块删除 + create_views 4 死函数删除，活函数保留）")
