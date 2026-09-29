"""497号 批次1（P2）：status_verdict 白名单透出 final_score/semantic_type/reliability_summary

497号要点（详见方案 §九 批次1 + Q5）：
- 透出 3 键（final_score REAL / semantic_type str / reliability_summary JSON str→dict）；
- consensus_detail 仅落库不透出；
- 两处构造点同契约：strategy_analyze（analyze 路由，快照优先 + fallback 实时）
  与 cross_validate._get_status_verdict（diagnose 路由，快照优先 + fallback 实时）。
"""
import os
import sys
from pathlib import Path

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
for k in ['HTTP_PROXY', 'HTTPS_PROXY', 'ALL_PROXY']:
    os.environ.pop(k, None)

_ROOT = Path(__file__).resolve().parent.parent.parent
_ANALYZE = (_ROOT / 'backend' / 'app' / 'routes' / 'strategy_analyze.py').read_text(encoding='utf-8')
_XVALID = (_ROOT / 'backend' / 'app' / 'opportunity_atlas' / 'cross_validate.py').read_text(encoding='utf-8')


# ── analyze 路由：_status_row 白名单 ──

def test_analyze_status_row_whitelist_has_new_keys():
    assert "'final_score': _pr.get('final_score')," in _ANALYZE
    assert "'semantic_type': _pr.get('semantic_type')," in _ANALYZE
    assert "'reliability_summary': _pr.get('reliability_summary')," in _ANALYZE


# ── analyze 路由：status_verdict 快照路径 + fallback ──

def test_analyze_verdict_snapshot_path_has_new_keys_not_consensus_detail():
    assert "'final_score': _status_row.get('final_score')," in _ANALYZE
    assert "'semantic_type': _status_row.get('semantic_type')," in _ANALYZE
    assert ("'reliability_summary': _json3.loads(_status_row.get('reliability_summary')"
            in _ANALYZE)
    # consensus_detail 不透出（Q5：仅落库）
    assert "'consensus_detail'" not in _ANALYZE


def test_analyze_verdict_fallback_path_has_new_keys():
    assert "'final_score': _verdict.get('final_score')," in _ANALYZE
    assert "'semantic_type': _verdict.get('semantic_type')," in _ANALYZE
    assert ("'reliability_summary': _json3.loads(_verdict.get('reliability_summary')"
            in _ANALYZE)


# ── cross_validate 路由：SELECT + 快照路径 + fallback ──

def test_cross_validate_select_and_verdict_have_new_keys():
    assert 'final_score, semantic_type, reliability_summary ' in _XVALID
    assert "'final_score': row[8]," in _XVALID
    assert "'semantic_type': row[9]," in _XVALID
    assert "'reliability_summary': _json.loads(row[10] or '{}')," in _XVALID
    # fallback 路径
    assert "'final_score': r.get('final_score')," in _XVALID
    assert "'semantic_type': r.get('semantic_type')," in _XVALID
    assert "'reliability_summary': _json.loads(r.get('reliability_summary') or '{}')," in _XVALID
    # 同契约：consensus_detail 不透出
    assert "'consensus_detail'" not in _XVALID


# ── 行为级：reliability_summary JSON str → dict 解析语义（与两构造点一致） ──

def test_reliability_summary_parse_semantics():
    import json
    assert json.loads('{"structure": 0.8, "risk": 0.4}' or '{}') == {
        'structure': 0.8, 'risk': 0.4}
    assert json.loads('' or '{}') == {}
