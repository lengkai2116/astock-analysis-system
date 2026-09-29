"""492号 P1 机械收敛 4 项回归

  P1-1  dim8 summary judgment 标注展示派生态（caliber=display_derived），保留展示契约键
  P1-2  cross_validate._get_status_verdict 优先读 status_snapshot 成品（不实时重算）
  P1-3  status_snapshot.signals（注册表触发）接入 status_verdict 展示
  P1-4  _apply_l0 移除未使用的 dims 形参
"""
import inspect
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.opportunity_atlas.cross_validate import L4CrossValidator  # noqa: E402
from app.opportunity_atlas.dimensions.dim8_summary_engine import Dim8SummaryEngine  # noqa: E402
from app.opportunity_atlas.status_engine import StatusEngine  # noqa: E402


def _dim_results_ok():
    return {
        'signal': {'status_description': {}, 'judgment': {'attribute': {'code': 'neutral'}},
                   'audit': {'confidence': 0.8}},
        'structure': {'status_description': {'vs_zhongshu': '上方', 'chanlun_direction': '上升'},
                      'judgment': {'structure': '上升', 'overall_direction': 1,
                                   'continuous_value': 0.7},
                      'audit': {'confidence': 0.8}},
        'volume_price': {'status_description': {'vp_state': '健康', 'volume_energy': '放量'},
                         'judgment': {'state': '健康', 'overall_direction': 1,
                                      'continuous_value': 0.7},
                         'audit': {'confidence': 0.8}},
        'chip_fund': {'status_description': {'phase': '拉升'},
                      'judgment': {'phase': 'lifting', 'direction': 'inflow',
                                   'overall_direction': 1, 'continuous_value': 0.6},
                      'audit': {'confidence': 0.7}},
        'emotion': {'status_description': {'market_phase': 'positive'},
                    'judgment': {'overall_direction': 1, 'continuous_value': 0.6},
                    'audit': {'confidence': 0.7}},
        'risk': {'status_description': {'risk_level': '低'},
                 'judgment': {'level': '低', 'overall_direction': 1, 'continuous_value': 0.6},
                 'audit': {'confidence': 0.8}},
        'valuation': {'status_description': {'valuation_level': '低估'},
                      'judgment': {'overall_direction': 1, 'continuous_value': 0.6},
                      'audit': {'confidence': 0.7}},
    }


# ── P1-1：dim8 judgment 标注展示派生 ──────────────────────────────────

def test_p1_1_dim8_judgment_marked_display_derived():
    r = Dim8SummaryEngine().evaluate(dims={}, tags={},
                                     lifecycle={'dim_results': _dim_results_ok()})
    jg = r['judgment']
    assert jg.get('caliber') == 'display_derived'
    # 展示契约键保留（test_436 依赖）
    for k in ('status_bar', 'consensus_rate', 'direction', 'overall_light'):
        assert k in jg


# ── P1-2：_get_status_verdict 优先读快照 ────────────────────────────

def test_p1_2_status_verdict_prefers_snapshot(monkeypatch):
    """有 status_snapshot 成品行 → 不触发实时 evaluate"""
    called = {'eval': 0}

    class _FakeCursor:
        def execute(self, *a, **k):
            return None

        def fetchone(self):
            # 顺序：opportunity_state, status_bar, consensus_rate, direction,
            #       conflict_evidence, dim_states, advice_params, signals,
            #       final_score, semantic_type, reliability_summary（497号 批次1 追加）
            return ('enter', '趋势确认', 0.82, 'bull', '[]', '{}', '{"s":1}',
                    '[{"type": "ma_bullish"}]', 78.5, '确认型', '{"structure":0.8}')

    class _FakeConn:
        def cursor(self):
            return _FakeCursor()

    import app.data.sharding_manager as sm

    class _SM:
        def get_db_for_table(self, t):
            return 'snapshot_cache.db'

        def get_connection(self, db):
            return _FakeConn()

    monkeypatch.setattr(sm, 'sharding_manager', _SM())

    from app.opportunity_atlas import status_engine as se_mod

    def _boom(self, ts_code, *a, **k):
        called['eval'] += 1
        raise AssertionError('不应实时重算')

    monkeypatch.setattr(se_mod.StatusEngine, 'evaluate', _boom)

    v = L4CrossValidator.__new__(L4CrossValidator)._get_status_verdict('000001.SZ')
    assert v['opportunity_state'] == 'enter'
    assert v['consensus_rate'] == 0.82
    assert v['advice_params'] == {'s': 1}
    assert v['signals'] == [{'type': 'ma_bullish'}]
    # 497号 批次1：v390 判定新字段透出（consensus_detail 不透）
    assert v['final_score'] == 78.5
    assert v['semantic_type'] == '确认型'
    assert v['reliability_summary'] == {'structure': 0.8}
    assert called['eval'] == 0


def test_p1_2_status_verdict_fallback_when_no_snapshot(monkeypatch):
    """无成品行 → 回退实时 evaluate"""
    class _FakeCursor:
        def execute(self, *a, **k):
            return None

        def fetchone(self):
            return None

    class _FakeConn:
        def cursor(self):
            return _FakeCursor()

    import app.data.sharding_manager as sm

    class _SM:
        def get_db_for_table(self, t):
            return 'snapshot_cache.db'

        def get_connection(self, db):
            return _FakeConn()

    monkeypatch.setattr(sm, 'sharding_manager', _SM())

    from app.opportunity_atlas import status_engine as se_mod

    class _FakeSE:
        def evaluate(self, ts_code, **k):
            return {'opportunity_state': 'wait', 'status_bar': '趋势不明',
                    'consensus_rate': 0.1, 'direction': 'neutral',
                    'conflict_evidence': '[]', 'dim_states': '{}',
                    'advice_params': '{}', 'signals': '[{"type": "ma_bullish"}]'}

    # 注入假引擎（避免真 StatusEngine 构造触发 DataManager 连库）
    monkeypatch.setattr(se_mod, 'StatusEngine', _FakeSE)

    v = L4CrossValidator.__new__(L4CrossValidator)._get_status_verdict('000001.SZ')
    assert v['opportunity_state'] == 'wait'
    assert v['signals'] == [{'type': 'ma_bullish'}]


# ── P1-3：signals 接入 status_snapshot / status_verdict ──────────────

def test_p1_3_signals_in_snapshot_row_and_verdict_contract():
    """_assemble 落 signals；前端 status_verdict 读取契约含 signals"""
    eng = StatusEngine.__new__(StatusEngine)
    eng.registry = {}
    l2 = {'opportunity_state': 'wait', 'state_evidence': [], 'consensus_rate': 0.3,
          'direction': 'neutral', 'conflict_evidence': [], 'final_score': 50.0,
          'semantic_type': '', 'reliability_summary': {}, 'consensus_detail': {},
          'advice': {'max_position_ratio': 0.2}}
    row = eng._assemble('000001.SZ', {}, None,
                        {'hold_only': False, 'position_coeff': 1.0,
                         'soft_risks': [], 'hard_veto': False}, l2,
                        [{'type': 'ma_bullish', 'name': '均线多头'}], None)
    assert json.loads(row['signals']) == [{'type': 'ma_bullish', 'name': '均线多头'}]

    # 前端契约：status_verdict 字段含 signals（读源码文本，避免导入路由模块触发 create_app）
    import pathlib
    _sa = pathlib.Path(__file__).resolve().parents[1] / 'app' / 'routes' / 'strategy_analyze.py'
    body = _sa.read_text(encoding='utf-8')
    assert "'signals': _json3.loads(_status_row.get('signals')" in body
    assert "'signals': _json3.loads(_verdict.get('signals')" in body


# ── P1-4：_apply_l0 形参清理 ─────────────────────────────────────────

def test_p1_4_apply_l0_signature_drops_dims():
    sig = inspect.signature(StatusEngine._apply_l0)
    params = list(sig.parameters)
    # 492号 P1-4 原意：清理未使用的 dims 形参（判定全部读 tags + daily_basic）
    assert params[:4] == ['self', 'ts_code', 'tags', 'lifecycle']
    assert 'dims' not in sig.parameters
    # 494号批次2：新增 raw_pre_feat=...（L0 市场级温度回升取数，R-1/R-9）——非 dims 回归
    assert params[4:] == ['raw_pre_feat']
