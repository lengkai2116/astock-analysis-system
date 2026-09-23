"""436号 B3 沙盒端到端验证：dim8 归集 → 分级门禁 → OUT 七维透传

按项目 AGENTS.md §六 数据隔离红线：用 tmp_path + ShardingManager + patch
sm_mod.sharding_manager 双切隔离，绝不触碰开发基准数据目录（data/duckdb）。

链路（对应 daemon 真实路径，非 mock）：
  1. Dim8SummaryEngine.build_seven_dim_report 从 dim_results 产 7 键报告
  2. QualityChecker.validate_signal_rows 分级门禁（硬 0 拦）
  3. 落 tmp strategy_signal_detail（7 键 seven_dim_json）
  4. OUT _out_transmit_seven_dim 真实函数 → one_liner_detail 透传富数据
"""
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
for k in ['HTTP_PROXY', 'HTTPS_PROXY', 'ALL_PROXY']:
    os.environ.pop(k, None)

import pytest


def _mk_dim_results():
    """构造全维齐备的 dim_results（signal→valuation 7 维富数据）"""
    base = {}
    for dim in ['signal', 'structure', 'volume_price', 'chip_fund',
                'emotion', 'risk', 'valuation']:
        base[dim] = {
            'judgment': {'overall_light': 'yellow', 'overall_direction': 0,
                         'continuous_value': 0.5},
            'status_description': {'plain': f'{dim}现状描述说明'},
            'audit': {'conditions': [{'name': f'{dim}条件1', 'satisfied': True},
                                     {'name': f'{dim}条件2', 'satisfied': False}],
                      'satisfied_count': 1, 'total_count': 2, 'confidence': 1.0},
        }
    return base


def _build_sig_row(ts_code, trade_date, dim_results: dict):
    """与 data_daemon 循环体对齐：dim8 归集 → (ts_code, trade_date, signal, ver, seven_dim, dim_results)"""
    from app.opportunity_atlas.dimensions.dim8_summary_engine import Dim8SummaryEngine
    seven_dim = Dim8SummaryEngine().build_seven_dim_report(dim_results, tags={})
    signal = json.dumps({'direction': 'up', 'score': 0.8})
    return (ts_code, trade_date, signal, 1,
            json.dumps(seven_dim, ensure_ascii=False) if seven_dim else None,
            json.dumps(dim_results, ensure_ascii=False, default=str))


def _setup_tmp_sharding(tmp_path, trade_date='2026-09-15'):
    """建隔离 ShardingManager + 分库表，patch 全局单例"""
    from app.data import sharding_manager as sm_mod
    from app.data.sharding_manager import ShardingManager

    tmp_sm = ShardingManager(tmp_path)
    (tmp_path / 'duckdb').mkdir(exist_ok=True)
    sm_mod.sharding_manager = tmp_sm  # 直接覆盖模块单例（_out_transmit 局部 import 此)

    # daily_cache（market_cache.db）——_out_transmit 用 MAX(trade_date) 定位交易日
    mc = tmp_sm.get_connection('market_cache.db')
    mc.execute("CREATE TABLE IF NOT EXISTS daily_cache (ts_code TEXT, trade_date TEXT, close REAL)")
    mc.execute("INSERT OR REPLACE INTO daily_cache (ts_code, trade_date, close) VALUES ('000001.SZ', ?, 1.0)", [trade_date])
    mc.commit()

    # strategy_signal_detail（snapshot_cache.db）——对齐 _batch_write_signal_detail 列序
    sc = tmp_sm.get_connection('snapshot_cache.db')
    sc.execute("""CREATE TABLE IF NOT EXISTS strategy_signal_detail (
        ts_code TEXT, trade_date TEXT, signal_json TEXT, schema_version INT,
        cached_at TEXT, seven_dim_json TEXT, dim_results_json TEXT)""")
    # status_snapshot——对齐 OUT UPDATE 目标列（ts_code/snapshot_date/trade_date/one_liner_detail）
    sc.execute("""CREATE TABLE IF NOT EXISTS status_snapshot (
        ts_code TEXT, snapshot_date TEXT, trade_date TEXT, one_liner_detail TEXT,
        dim_states TEXT, status_bar TEXT)""")
    sc.commit()
    return tmp_sm


# ── 1. 归集 → 门禁：硬 0 拦 ────────────────────────────────

def test_dim8_report_passes_gate_and_has_seven_keys():
    from app.data.stg_quality import QualityChecker
    dr = _mk_dim_results()
    row = _build_sig_row('000001.SZ', '2026-09-15', dr)
    checker = QualityChecker()
    issues = checker.validate_signal_rows([row])
    assert issues == [], f'全维报告应通过硬门禁，实际: {issues}'
    sd = json.loads(row[4])
    # 479号：signal 段按 2026-09-15 裁决由 JUD 单独路径产出（dim8 SEVEN_DIM_SPEC 无 signal，
    #   436 B1 契约 7 键 → dim8 实产 6 键；门禁段数≥6 即过）
    assert set(sd.keys()) == {'structure', 'volume_price',
                              'fund_chip', 'emotion', 'risk', 'summary'}
    # 灯色 emoji + judgment 颜色名双轨
    for seg in sd.values():
        assert seg['light'] in ('🟢', '🔴', '🟡')
        assert seg['judgment']['overall_light'] in ('green', 'red', 'yellow')


# ── 2. 缺维：段不产但 summary 恒有；B4 门禁段数<6 硬拦 ─────

def test_partial_dims_pass_gate_summary_present():
    from app.data.stg_quality import QualityChecker
    dr = _mk_dim_results()
    dr.pop('structure', None)   # 模拟引擎偶发缺维
    row = _build_sig_row('000002.SZ', '2026-09-15', dr)
    checker = QualityChecker()
    sd = json.loads(row[4])
    # 437-A D7：缺维不产段，summary 恒在
    assert 'summary' in sd and 'structure' not in sd
    # 479号：B4 门禁终态（段数≥6 硬拦）——缺维致 5 键 → 硬拦 → daemon SIG failed → 管道重试
    issues = checker.validate_signal_rows([row])
    assert any('段数不足' in i for i in issues), f'缺维 5 键应被 B4 硬拦，实际: {issues}'


# ── 3. OUT 七维透传（真实 _out_transmit_seven_dim）─────────

def test_out_transmit_flows_seven_dim_to_one_liner(monkeypatch, tmp_path):
    dr = _mk_dim_results()
    row = _build_sig_row('000001.SZ', '2026-09-15', dr)
    tmp_sm = _setup_tmp_sharding(tmp_path)
    sc = tmp_sm.get_connection('snapshot_cache.db')
    # 落 strategy_signal_detail（7 键）
    sc.execute("INSERT OR REPLACE INTO strategy_signal_detail VALUES (?,?,?,?,datetime('now','localtime'),?,?)",
               (row[0], row[1], row[2], row[3], row[4], row[5]))
    # status_snapshot 初始 one_liner_detail NULL
    sc.execute("INSERT OR REPLACE INTO status_snapshot (ts_code, snapshot_date, trade_date, one_liner_detail) "
               "VALUES ('000001.SZ', '2026-09-15', '2026-09-15', NULL)")
    sc.commit()

    # 隔离 ECM：避免 get_ecm_instance 指向真实库
    import sqlite3
    from app.data.enhanced_cache_manager import EnhancedCacheManager
    fake_ecm = EnhancedCacheManager.__new__(EnhancedCacheManager)
    fake_ecm.conn = sqlite3.connect(str(tmp_path / 'stock_cache.db'))
    fake_ecm.conn.execute("CREATE TABLE IF NOT EXISTS watchlist_status_diff "
                          "(ts_code TEXT NOT NULL, snapshot_date TEXT NOT NULL)")
    fake_ecm.conn.commit()

    # import data_daemon 前确保 DATA_DIR 指向 tmp（模块顶部 setdefault 才不覆盖）
    os.environ['DATA_DIR'] = str(tmp_path)
    import data_daemon as dd
    monkeypatch.setattr(dd, '_ecm', fake_ecm)

    dd._out_transmit_seven_dim(['000001.SZ'])

    # 断言 one_liner_detail 已透传富数据
    out = sc.execute(
        "SELECT one_liner_detail FROM status_snapshot WHERE ts_code='000001.SZ'").fetchone()
    assert out and out[0], 'one_liner_detail 应为非空（dim8 6 键透传）'
    sd = json.loads(out[0])
    # 479号：signal 段由 JUD 单独产出（2026-09-15 裁决），dim8 契约 6 键
    assert set(sd.keys()) >= {'structure', 'volume_price',
                              'fund_chip', 'emotion', 'risk', 'summary'}
    sc.close()


# ── 4. 门禁：结构性缺陷硬拦（回归 §5.2）───────────────────

def test_gate_blocks_segment_missing_text(tmp_path):
    from app.data.stg_quality import QualityChecker
    row = list(_build_sig_row('000003.SZ', '2026-09-15', _mk_dim_results()))
    sd = json.loads(row[4])
    del sd['summary']['text']          # 段缺 text → 硬拦
    row[4] = json.dumps(sd, ensure_ascii=False)
    issues = QualityChecker().validate_signal_rows([tuple(row)])
    assert any('缺字段 text' in i for i in issues)
