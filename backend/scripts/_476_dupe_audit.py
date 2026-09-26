"""476 遗留差异审计 v3：AST unparse 级对比（彻底剔除注释/docstring/格式噪声）

ast.unparse 生成规范代码 → SequenceMatcher，相似度反映真实代码结构差异。
"""
import ast
import sys
import os
from difflib import SequenceMatcher

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

DIM7 = os.path.join(os.path.dirname(__file__), '..', 'app', 'opportunity_atlas',
                    'dimensions', 'dim7_valuation_engine.py')
EST = os.path.join(os.path.dirname(__file__), '..', 'app', 'opportunity_atlas',
                   'valuation_estimator.py')

PAIRS = [
    ('_category', '_category', '行业七类映射'),
    ('_anchor_pb', '_anchor_pb', '资产锚PB'),
    ('_anchor_earnings', '_anchor_earnings', '收益锚PE/PEG/股息'),
    ('_anchor_cashflow', '_anchor_cashflow', '现金流锚FCF/EV'),
    ('_anchor_adjusted_pe', '_anchor_adjusted_pe', '修正锚调整PE'),
    ('_fina_health', '_fina_health', '财务健康'),
    ('_anchor_bond_stock', '_anchor_bond_stock', '股债差锚'),
    ('_yoY_growth', '_yoY_growth', '同比增速(PEG依赖)'),
]


def _funcs(path: str) -> dict:
    with open(path) as f:
        tree = ast.parse(f.read())
    out = {}
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            out[node.name] = ast.unparse(node)
    return out


def _uniq(na: str, nb: str):
    """unparse 差异行（等长对齐输出）"""
    a_l, b_l = na.splitlines(), nb.splitlines()
    out = []
    sm = SequenceMatcher(None, a_l, b_l)
    for op, i1, i2, j1, j2 in sm.get_opcodes():
        if op == 'equal':
            continue
        for k in range(i1, i2):
            out.append(f'  dim7 | {a_l[k]}')
        for k in range(j1, j2):
            out.append(f'  EST  | {b_l[k]}')
    return out


def main():
    f7, fe = _funcs(DIM7), _funcs(EST)
    print(f"{'方法':<22}{'相似度':<9} 结论")
    print('-' * 70)
    for d7, est, note in PAIRS:
        a, b = f7.get(d7), fe.get(est)
        if not a:
            print(f'{d7:<22}  dim7 缺失'); continue
        if not b:
            print(f'{d7:<22}  EST 缺失（dim7 独有）'); continue
        r = SequenceMatcher(None, a, b).ratio()
        verdict = '✅ 一致' if r >= 0.99 else ('⚠️ 微差' if r >= 0.95 else '🔴 差异')
        print(f'{d7:<22}{r:<9.4f} {verdict} ({note})')
        if r < 0.99:
            for dl in _uniq(a, b)[:20]:
                print(dl)
            print()


if __name__ == '__main__':
    main()
