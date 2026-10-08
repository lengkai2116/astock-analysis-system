"""509号批次6：daemon JUD 工序段修复验证（#J43~#J46）

方案档：`002-方案存档/509-JUD板块OCR核查与处置.md` §9.8。

批次6 实施范围（2026-10-08）：
  #J43 `data_daemon._build_treemap_snapshot`/`_build_status_snapshot`：原子切换
      由「DROP + RENAME 两条独立 DDL」改为「RENAME 备份 → RENAME live → 删备份」
      （DROP 成功而 RENAME 失败会丢 live 表；新法任一步失败旧表仍可恢复）；
  #J44 `_build_treemap_snapshot`：close 缺失（停牌）时 `_safe_float` 返回 None →
      `max(None, 1e-9)` 抛 TypeError 被吞 → 该股静默丢出 treemap；缺 close 时
      amplitude 落 None 保留该股行；
  #J45 `_jud_enrich_with_meta`：逐股富化 3 处内层静默 except + 外层 continue
      加带 ts_code 的 warning/debug 定位日志（原全静默无法诊断）；
  #J46 `_verify_out_completeness`：once-guard——pipeline_status 本日已
      OUT-CHECK done 则跳过（原每次驱动重跑全表 COUNT）。

注：data_daemon 运行期不做全量回归；本探针为 AST/源码级断言 + 函数级单测。
"""
import ast
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest  # noqa: E402

DAEMON = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                      'data_daemon.py')


def _src():
    return open(DAEMON, encoding='utf-8').read()


def _func_ast(name: str) -> ast.FunctionDef:
    tree = ast.parse(_src())
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name == name:
            return node
    raise AssertionError(f'data_daemon 缺函数 {name}')


def _func_src(name: str) -> str:
    """提取函数源码片段（按行号区间）"""
    lines = _src().splitlines()
    node = _func_ast(name)
    return '\n'.join(lines[node.lineno - 1:node.end_lineno])


# ── #J43：原子切换改为 RENAME 备份序列 ──────────────────────

def test_j43_treemap_atomic_swap_no_drop_first():
    """treemap 原子切换不再先 DROP live 表（RENAME 备份 → RENAME live → 删备份）"""
    src = _func_src('_build_treemap_snapshot')
    # 不得有「DROP treemap_snapshot」（裸删 live 表；备份表 DROP 是 _bak 后缀，允许）
    assert 'DROP TABLE IF EXISTS treemap_snapshot"' not in src
    assert 'DROP TABLE IF EXISTS treemap_snapshot ' not in src
    assert 'RENAME TO treemap_snapshot_bak' in src
    assert 'RENAME TO treemap_snapshot' in src
    assert 'DROP TABLE IF EXISTS treemap_snapshot_bak' in src
    # 顺序：先备份旧表，再切换 live，最后删备份
    # 注意 `RENAME TO treemap_snapshot` 是 `..._bak` 变体的子串 → live 用带收尾引号精确匹配
    i_bak = src.index('RENAME TO treemap_snapshot_bak')
    i_live = src.index('RENAME TO treemap_snapshot")')
    i_drop = src.index('DROP TABLE IF EXISTS treemap_snapshot_bak')
    assert i_bak < i_live < i_drop, '切换顺序应为 备份→live→删备份'


def test_j43_status_atomic_swap_no_drop_first():
    """status_snapshot 原子切换同 treemap 模式"""
    src = _func_src('_build_status_snapshot')
    assert 'DROP TABLE IF EXISTS status_snapshot"' not in src
    assert 'DROP TABLE IF EXISTS status_snapshot ' not in src
    assert 'RENAME TO status_snapshot_bak' in src
    assert 'RENAME TO status_snapshot' in src
    assert 'DROP TABLE IF EXISTS status_snapshot_bak' in src


# ── #J44：close 缺失守卫 ────────────────────────────────────

def test_j44_treemap_close_missing_guard():
    """treemap amplitude 不再对 None close 直接 max(None, 1e-9)（TypeError 吞错丢股）"""
    src = _func_src('_build_treemap_snapshot')
    # 不再有裸 `max(_safe_float(d.get('close')), 1e-9)`（None → TypeError）
    assert 'max(_safe_float(d.get(\'close\')), 1e-9)' not in src
    # 先取 _close_f 再判 None
    assert '_close_f = _safe_float(d.get(\'close\'))' in src
    assert '_close_f is not None else None' in src


# ── #J45：富集循环定位日志 ──────────────────────────────────

def test_j45_enrich_logs():
    """逐股富化循环 3 处内层 + 外层 continue 均有带 ts_code 的日志"""
    src = _func_src('_jud_enrich_with_meta')
    # 外层 continue 前有 warning（原 except Exception: continue 静默）
    assert 'JUD 富化 {code} 失败（跳过该股）' in src
    # 内层 3 处（opportunity_meta / right_side_confirm / potential）
    assert 'opportunity_meta 失败' in src
    assert 'right_side_confirm 失败' in src
    assert 'potential 失败' in src
    # 内层不再有裸 `except Exception:\n pass`（本轮目标 3 处已全部命名）
    assert '\n                except Exception:\n                    pass\n' not in src


# ── #J46：OUT-CHECK once-guard ──────────────────────────────

def test_j46_out_check_guard():
    """_verify_out_completeness 开头查 pipeline_status 已有 done 则跳过"""
    src = _func_src('_verify_out_completeness')
    assert "step_id='OUT-CHECK'" in src or '"OUT-CHECK"' in src
    assert "if _prev and _prev[0] == 'done'" in src
    assert '跳过' in src
