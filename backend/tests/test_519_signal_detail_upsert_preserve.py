"""519号 定向测试：strategy_signal_detail 骨架行（影子行）顶掉 MAX(trade_date) 的处置。

- **A 写方**：`EnhancedCacheManager.cache_signal_detail` 写语义由 `INSERT OR REPLACE`
  改为 UPSERT（`ON CONFLICT(ts_code, trade_date) DO UPDATE`）——同键只更新 SIG 列
  （signal_json/schema_version/cached_at），**保留**既有 seven_dim_json/dim_results_json；
  根治「单只预计算（precompute_strategy）在日终产物已落库后触发即抹掉 JUD 产物」。
- **B 消费侧**：按「MAX(trade_date) ∧ dim_results_json 非空」取数，避免骨架行致误判无数据。
"""
import inspect
import pathlib
import re

from app.data.sharding_manager import ShardingManager

_DDL = (
    "CREATE TABLE IF NOT EXISTS strategy_signal_detail ("
    " ts_code TEXT NOT NULL, trade_date TEXT NOT NULL, signal_json TEXT NOT NULL,"
    " schema_version INTEGER DEFAULT 1,"
    " cached_at TEXT DEFAULT (datetime('now','localtime')),"
    " seven_dim_json TEXT DEFAULT NULL, dim_results_json TEXT DEFAULT NULL,"
    " PRIMARY KEY (ts_code, trade_date))"
)

_SEED_SQL = (
    "INSERT OR REPLACE INTO strategy_signal_detail "
    "(ts_code, trade_date, signal_json, schema_version, cached_at, seven_dim_json, dim_results_json) "
    "VALUES (?, ?, ?, ?, ?, ?, ?)"
)

_SELECT_SQL = (
    "SELECT signal_json, seven_dim_json, dim_results_json FROM strategy_signal_detail "
    "WHERE ts_code=? AND trade_date=?"
)


def _mgr(tmp_path):
    (tmp_path / 'duckdb').mkdir(exist_ok=True)
    return ShardingManager(str(tmp_path))


def test_source_uses_upsert_not_or_replace():
    """写方 SQL 必须是 UPSERT，不得再用 INSERT OR REPLACE（否则同键 JUD 产物被置 NULL）。"""
    from app.data.enhanced_cache_manager import EnhancedCacheManager
    src = inspect.getsource(EnhancedCacheManager.cache_signal_detail)
    assert 'ON CONFLICT(ts_code, trade_date) DO UPDATE' in src, "应使用 UPSERT"
    assert 'INSERT OR REPLACE INTO strategy_signal_detail' not in src, "不得再用 INSERT OR REPLACE"


def test_upsert_preserves_jud_columns(tmp_path, monkeypatch):
    """已落库（JUD 产物非空）的行，被单只预计算重写 SIG 列后，seven_dim_json/dim_results_json 应保留。"""
    sm = _mgr(tmp_path)
    sm.create_table('strategy_signal_detail', _DDL)
    # 预置一条「日终 SIG/JUD 已落库」的完整行
    sm.execute_batch_insert(
        'strategy_signal_detail', _SEED_SQL,
        [('000001.SZ', '2026-10-13', '{"old": 1}', 1, '2026-10-13 20:00:00',
          '{"seven": 1}', '{"dim": 1}')])
    monkeypatch.setattr('app.data.sharding_manager.sharding_manager', sm)

    from app.data.enhanced_cache_manager import EnhancedCacheManager
    ecm = EnhancedCacheManager.__new__(EnhancedCacheManager)  # cache_signal_detail 不依赖实例状态
    ecm.cache_signal_detail('000001.SZ', {'trade_date': '2026-10-13', 'signals': {'x': 1}})

    row = sm.execute_query('strategy_signal_detail', _SELECT_SQL, ['000001.SZ', '2026-10-13'])[0]
    signal_json, seven_dim_json, dim_results_json = row
    assert seven_dim_json == '{"seven": 1}', f"seven_dim_json 应保留，实际 {seven_dim_json!r}"
    assert dim_results_json == '{"dim": 1}', f"dim_results_json 应保留，实际 {dim_results_json!r}"
    assert '"x"' in signal_json, f"signal_json 应被更新，实际 {signal_json!r}"
    sm.close_all()


def test_upsert_inserts_skeleton_row_when_absent(tmp_path, monkeypatch):
    """无既有行时应正常插入骨架行（含 NULL JUD 列）——行为与旧一致，仅不覆盖既有产物。"""
    sm = _mgr(tmp_path)
    sm.create_table('strategy_signal_detail', _DDL)
    monkeypatch.setattr('app.data.sharding_manager.sharding_manager', sm)

    from app.data.enhanced_cache_manager import EnhancedCacheManager
    EnhancedCacheManager.__new__(EnhancedCacheManager).cache_signal_detail(
        '600519.SH', {'trade_date': '2026-10-13', 'signals': {}})

    row = sm.execute_query('strategy_signal_detail', _SELECT_SQL, ['600519.SH', '2026-10-13'])
    assert len(row) == 1, "应插入新骨架行"
    assert row[0][1] is None and row[0][2] is None, "骨架行 JUD 列应为 NULL"
    sm.close_all()


def test_consume_side_filters_null_json():
    """B 消费侧：5 处取「最新交易日」的查询须带 dim_results_json IS NOT NULL 过滤。"""
    root = pathlib.Path(__file__).resolve().parents[1]
    needle = 'MAX(trade_date) FROM strategy_signal_detail WHERE dim_results_json IS NOT NULL'
    targets = (
        'tests/test_495_b2_jud_market_gate.py',
        'scripts/_495_b2_jud_market_gate.py',
        'scripts/_495_b6_b3_probe.py',
        'test_395_real_data.py',
        'app/routes/health.py',
    )
    for rel in targets:
        txt = (root / rel).read_text(encoding='utf-8')
        flat = re.sub(r'\s+', ' ', txt.replace('"', ' ').replace("'", ' '))
        assert needle in flat, f"{rel} 的 MAX(trade_date) 应带 dim_results_json IS NOT NULL 过滤"
