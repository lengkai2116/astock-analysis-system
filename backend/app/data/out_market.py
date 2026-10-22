"""541号 B1：仪表盘市场级 OUT 成品仓（out_market_panel）。

规则（B0 定稿）：
- 展示类数据只能读 OUT 成品仓；
- 本表由 OUT 步骤构建，存仪表盘各 EOD 模块的完整 payload；
- 盘中实时字段不写入本表，由 API 层按白名单 overlay（B3 实施）。

本模块只做纯逻辑：模块契约、payload 校验、日期提取、分库读写。
不依赖 Flask / DataManager，便于单测。
"""
from __future__ import annotations

import json
import logging
import threading
from datetime import datetime

logger = logging.getLogger(__name__)

# 模块 → 必须存在的顶层键（与 dashboard_service 返回结构对齐）
OUT_MARKET_MODULES: dict[str, tuple[str, ...]] = {
    'market_index_daily': ('days',),
    'market_daily_top_up': ('stocks', 'type'),
    'market_daily_top_down': ('stocks', 'type'),
    'market_eod_snapshot': ('stocks', 'trade_date'),
    'market_overview_panel': ('as_of', 'breadth'),
    'market_moneyflow_summary': ('days',),
    'market_sector_changes': ('gainers', 'losers', 'date'),
    'market_sector_moneyflow': ('sectors', 'date'),
    'market_flows_30d': ('industry_flow_5d', 'margin_30d', 'etf_30d'),
    'market_breadth': ('up_count', 'down_count', 'trade_date'),
    'market_limit_ecology': ('up', 'down', 'as_of'),
    'market_state': ('state', 'state_label', 'data_date'),
    'market_emotion': ('phase', 'phase_label', 'data_date'),
    'market_sector_heat': ('sectors', 'date'),
    'market_sector_heat_dim': ('sectors', 'date'),
    'market_alerts': ('alerts', 'date'),
    'market_overview': ('indexes',),
}

# 允许空值/空列表的键（当天无预警、单边行情下涨/跌榜可能为空）
_ALLOW_EMPTY_KEYS = {'alerts', 'gainers', 'losers'}

# 从 payload 中提取各模块自带的日期口径（供前端逐模块标注）
_DATE_KEYS = {
    'trade_date', 'data_date', 'as_of', 'date', 'stat_date',
    'prev_trade_date', 'prev_date', 'updated_at', 'cached_at',
}


# 541 B4：get_tags 以 treemap_snapshot（OUT 成品）覆盖的判定字段
OUT_TAG_FIELDS = (
    'signal_strength', 'opportunity_state', 'right_side_confirm',
    'opportunity_label', 'opportunity_type', 'opportunity_profile',
    'confirm_evidence', 'state_evidence', 'entry_signals', 'exit_conditions',
    'main_force_presence', 'presence_evidence', 'consensus_rate', 'conflict',
)


def apply_tag_overlay(tags: dict, row: dict | None) -> dict:
    """用 treemap_snapshot 行覆盖旧标签中的 OUT 判定字段。

    - row 为空：显式清空 state/rsc/label/signal_strength，避免回落到 08-19 旧值；
    - row 存在：覆盖白名单字段；None/NaN 也覆盖为 None（不保留旧值）。
    """
    out = dict(tags or {})
    if not row:
        for key in ('signal_strength', 'opportunity_state',
                    'right_side_confirm', 'opportunity_label'):
            out[key] = None
        return out

    for key in OUT_TAG_FIELDS:
        if key not in row:
            continue
        value = row.get(key)
        try:
            if value is not None and value != value:  # NaN（含 numpy float）
                value = None
        except (TypeError, ValueError):
            pass
        if key == 'signal_strength':
            out[key] = None if value is None else str(value)
        else:
            out[key] = value
    return out


def validate_payload(module: str, payload) -> tuple[bool, str]:
    """校验单个模块 payload 是否符合 OUT 成品仓契约。

    Returns: (ok, reason)。reason 为空表示通过。
    """
    required = OUT_MARKET_MODULES.get(module)
    if required is None:
        return False, f'未登记的模块: {module}'
    if not isinstance(payload, dict) or not payload:
        return False, 'payload 为空或非 dict'

    missing = [k for k in required if k not in payload]
    if missing:
        return False, f"缺字段 {missing}"

    for key in required:
        value = payload.get(key)
        if key in _ALLOW_EMPTY_KEYS:
            continue
        if value is None:
            return False, f'字段 {key} 为 None'
        if isinstance(value, (list, dict, str)) and len(value) == 0:
            return False, f'字段 {key} 为空'
    return True, ''


def extract_dates(payload) -> dict[str, str]:
    """从 payload 中收集日期类字段（每个键取最大字符串），用于 data_dates_json。"""
    found: dict[str, set[str]] = {}

    def _walk(node, depth: int = 0):
        if depth > 3:
            return
        if isinstance(node, dict):
            for key, value in node.items():
                if key in _DATE_KEYS and isinstance(value, (str, int, float)):
                    text = str(value).strip()
                    if text and text.lower() not in ('nan', 'none', 'nat'):
                        found.setdefault(key, set()).add(text[:19])
                elif isinstance(value, (dict, list)):
                    _walk(value, depth + 1)
        elif isinstance(node, list):
            for item in node[:20]:
                if isinstance(item, (dict, list)):
                    _walk(item, depth + 1)

    _walk(payload)
    return {key: sorted(values)[-1] for key, values in found.items() if values}


def ensure_table(conn) -> None:
    """确保 out_market_panel 存在（snapshot_cache.db 分库）。"""
    conn.execute("""
        CREATE TABLE IF NOT EXISTS out_market_panel (
            module          TEXT NOT NULL,
            asof_date       TEXT NOT NULL,
            payload_json    TEXT NOT NULL,
            data_dates_json TEXT,
            schema_version  INTEGER DEFAULT 1,
            built_at        TEXT,
            PRIMARY KEY (module, asof_date)
        )
    """)
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_out_market_panel_module "
        "ON out_market_panel(module, asof_date)"
    )
    conn.commit()


def _db_name(sharding_manager) -> str:
    return sharding_manager.get_db_for_table('out_market_panel') or 'snapshot_cache.db'


# 建表只需一次/进程；避免每次读都执行 DDL+commit（B2 高频读）
_ENSURED_DBS: set[str] = set()
_ENSURE_LOCK = threading.Lock()


def _ensure_once(sharding_manager, db_name: str) -> None:
    if db_name in _ENSURED_DBS:
        return
    with _ENSURE_LOCK:
        if db_name in _ENSURED_DBS:
            return
        ensure_table(sharding_manager.get_connection(db_name))
        _ENSURED_DBS.add(db_name)


def upsert_panel(sharding_manager, module: str, asof_date: str, payload: dict,
                 data_dates: dict | None = None, schema_version: int = 1) -> bool:
    """写入/覆盖单模块成品（仅 OUT 构建器调用）。"""
    try:
        db_name = _db_name(sharding_manager)
        _ensure_once(sharding_manager, db_name)
        conn = sharding_manager.get_connection(db_name)
        payload_json = json.dumps(payload, ensure_ascii=False, default=str)
        data_dates_json = json.dumps(data_dates or {}, ensure_ascii=False, default=str)
        built_at = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        lock = sharding_manager.get_write_lock(db_name)
        with lock:
            conn.execute(
                "INSERT OR REPLACE INTO out_market_panel "
                "(module, asof_date, payload_json, data_dates_json, schema_version, built_at) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                [module, asof_date, payload_json, data_dates_json,
                 int(schema_version), built_at],
            )
            conn.commit()
        return True
    except Exception as exc:
        logger.warning(f"out_market_panel 写入失败 [{module}/{asof_date}]: {exc}")
        return False


def get_panel(sharding_manager, module: str, asof_date: str | None = None) -> dict | None:
    """读取单模块成品；asof_date 为空时取最新一行。"""
    try:
        db_name = _db_name(sharding_manager)
        _ensure_once(sharding_manager, db_name)
        read_conn = sharding_manager.get_read_connection(db_name)
        if asof_date:
            row = read_conn.execute(
                "SELECT module, asof_date, payload_json, data_dates_json, "
                "schema_version, built_at FROM out_market_panel "
                "WHERE module=? AND asof_date=?",
                [module, asof_date],
            ).fetchone()
        else:
            row = read_conn.execute(
                "SELECT module, asof_date, payload_json, data_dates_json, "
                "schema_version, built_at FROM out_market_panel "
                "WHERE module=? ORDER BY asof_date DESC LIMIT 1",
                [module],
            ).fetchone()
        if not row:
            return None
        try:
            payload = json.loads(row[2]) if row[2] else None
        except (TypeError, ValueError):
            logger.warning(f"out_market_panel payload 解析失败 [{module}/{row[1]}]")
            return None
        try:
            data_dates = json.loads(row[3]) if row[3] else {}
        except (TypeError, ValueError):
            data_dates = {}
        return {
            'module': row[0],
            'asof_date': row[1],
            'payload': payload,
            'data_dates': data_dates,
            'schema_version': row[4],
            'built_at': row[5],
        }
    except Exception as exc:
        logger.warning(f"out_market_panel 读取失败 [{module}]: {exc}")
        return None


def get_latest_asof_date(sharding_manager) -> str | None:
    """最新成品日（用于“最后一次有效版本”提示）。"""
    try:
        db_name = _db_name(sharding_manager)
        _ensure_once(sharding_manager, db_name)
        read_conn = sharding_manager.get_read_connection(db_name)
        row = read_conn.execute(
            "SELECT MAX(asof_date) FROM out_market_panel").fetchone()
        return str(row[0]) if row and row[0] else None
    except Exception as exc:
        logger.warning(f"out_market_panel 最新日期读取失败: {exc}")
        return None
