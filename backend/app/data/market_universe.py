"""个股宇宙 SSOT —— 剔除指数代码（483号 A1）

统一「个股宇宙」定义：
  - 宽基指数 BROAD_INDEX_CODES（438号缺口①：HS300 等）
  - 申万一级行业指数 SW_INDEX_CODES（438号缺口②）
  - 通用段规则：`.SI` 后缀（申万指数）/ `399` 开头（深市指数段）

背景：该剔除规则原散落多处内联实现（data_daemon._get_active_codes / 441 回补脚本 /
QA 覆盖率基准），不统一致 QA 分母混入指数 —— indicator_ma 报「5510/5536」假失败、
margin_cache 基准 5312（> 融资融券可交易集 ~4451）结构性恒失败（483 ④/③b）。本模块为唯一定义。

注意：019/000001.SH 是上证指数，但 000001.SZ 是平安银行 —— 交易所后缀不可忽略，
故宽基指数用显式清单而非「000001 段」规则。
"""

# 四大宽基指数代码（438号缺口①修复：HS300/000300.SH 为全系统相对强弱基准）
BROAD_INDEX_CODES = (
    '000001.SH', '000300.SH', '399001.SZ', '399006.SZ', '899050.BJ',
)

# 申万一级行业指数代码（31 个，SW2021 全量；438号缺口②修复）
SW_INDEX_CODES = (
    '801010.SI', '801030.SI', '801040.SI', '801050.SI', '801080.SI',
    '801110.SI', '801120.SI', '801130.SI', '801140.SI', '801150.SI',
    '801160.SI', '801170.SI', '801180.SI', '801200.SI', '801210.SI',
    '801230.SI', '801710.SI', '801720.SI', '801730.SI', '801740.SI',
    '801750.SI', '801760.SI', '801770.SI', '801780.SI', '801790.SI',
    '801880.SI', '801890.SI', '801950.SI', '801960.SI', '801970.SI',
    '801980.SI',
)

_INDEX_CODE_SET = frozenset(BROAD_INDEX_CODES) | frozenset(SW_INDEX_CODES)


def is_index_code(code: str) -> bool:
    """判断是否为指数代码（宽基 / 申万行业 / .SI 后缀 / 399 深市指数段）"""
    if not code:
        return False
    return (code in _INDEX_CODE_SET
            or code.endswith('.SI')
            or code.startswith('399'))


def stock_only_sql(alias: str = '') -> tuple:
    """返回 (sql_predicate, params)：可直接拼入 WHERE 的「仅个股」条件。

    Args:
        alias: 表别名（如 'd'），为空则用裸列名 ts_code
    """
    col = f'{alias}.ts_code' if alias else 'ts_code'
    placeholders = ', '.join('?' * len(_INDEX_CODE_SET))
    sql = (f"{col} NOT LIKE '%.SI' AND {col} NOT LIKE '399%' "
           f"AND {col} NOT IN ({placeholders})")
    return sql, sorted(_INDEX_CODE_SET)
