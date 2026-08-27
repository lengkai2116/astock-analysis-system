"""
因子库API路由
提供因子列表、计算、组合管理等功能
文件路径：backend/app/routes/factors.py

219 规格书对齐：响应结构遵循 §2.2-§2.7 字段映射
§13 数据完整性约束：所有数据不可用场景返回 503/4xx，不假造数据
"""
from flask import Blueprint, request, jsonify, current_app
import pandas as pd
import json
from datetime import datetime
import os
import logging
from sqlalchemy import create_engine

from app.factors import get_factor_registry, FactorCalculator
from app.data.factor_precompute import FactorPrecomputeManager
from app.data.enhanced_cache_manager import EnhancedCacheManager
from app.evaluation import FactorEvaluator
from app.engine import BacktestEngine, calculate_performance_metrics, get_strategy_pipeline

from app.utils.error_handlers import handle_exceptions, safe_db_operation

factors_bp = Blueprint('factors', __name__, url_prefix='/api/factors')

logger = logging.getLogger(__name__)

registry = get_factor_registry()
calculator = FactorCalculator()
cache_manager = EnhancedCacheManager()
precompute_manager = FactorPrecomputeManager(cache_manager)
evaluator = FactorEvaluator()


def get_db_path():
    """获取因子组合专用数据库路径（独立 SQLite 文件，与 duckdb 缓存分开）"""
    return os.path.join(os.getenv('DATA_DIR', '/data'), 'factors_combos.db')


# ══════════════════════════════════════════════════════════════
# RL5 合规：通过 SQLAlchemy 引擎管理 factors_combos.db 连接
# 不直接使用 sqlite3.connect()，统一走 SQLAlchemy 连接池
# ══════════════════════════════════════════════════════════════
_combo_engine = None


def _get_combo_engine():
    """获取因子组合数据库的 SQLAlchemy 引擎（延迟初始化、单例）"""
    global _combo_engine
    if _combo_engine is None:
        db_path = os.path.abspath(get_db_path())
        os.makedirs(os.path.dirname(db_path) or '.', exist_ok=True)
        _combo_engine = create_engine(
            f"sqlite:///{db_path}",
            echo=False,
            pool_pre_ping=True,
        )
    return _combo_engine


def _get_combo_conn():
    """获取因子组合数据库连接（通过 SQLAlchemy 引擎，RL5 合规）"""
    return _get_combo_engine().raw_connection()


_COMBO_DB_INIT = False


def _ensure_combo_db():
    """确保因子组合数据库表存在"""
    global _COMBO_DB_INIT
    if _COMBO_DB_INIT:
        return
    _get_combo_engine()  # 确保引擎已初始化、目录已创建
    conn = _get_combo_conn()
    try:
        cursor = conn.cursor()
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS factor_combinations (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                description TEXT DEFAULT '',
                factors TEXT DEFAULT '[]',
                type TEXT DEFAULT 'user',
                src TEXT DEFAULT '用户自建',
                detail TEXT,
                is_default INTEGER DEFAULT 0,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        conn.commit()
        _COMBO_DB_INIT = True
    finally:
        conn.close()


# ══════════════════════════════════════════════════════════════
# 常量定义 — 与 219 规格书对齐
# ══════════════════════════════════════════════════════════════

CATEGORY_CN_MAP = {
    "momentum":    {"cn": "📈 价格动量", "order": 1},
    "reversal":    {"cn": "🔄 超买超卖", "order": 2},
    "volume":      {"cn": "💧 成交量资金", "order": 3},
    "trend":       {"cn": "📊 趋势追踪", "order": 4},
    "volatility":  {"cn": "🌊 波动率", "order": 5},
    "position":    {"cn": "📍 价格位置", "order": 6},
    "academic":    {"cn": "📐 统计指标", "order": 7},
    "qlib":        {"cn": "📐 QLib 标准因子", "order": 8},
    "alpha101":    {"cn": "⚡ WorldQuant Alpha", "order": 9},
    "fundamental": {"cn": "🏢 基本面", "order": 10},
    "sentiment":   {"cn": "😊 情绪感知", "order": 11},
    "size":        {"cn": "🏋️ 规模", "order": 12},
    "value":       {"cn": "💎 价值", "order": 13},
    "growth":      {"cn": "🌱 成长", "order": 14},
    "quality":     {"cn": "✅ 质量", "order": 15},
}

PRESET_COMBOS = [
    {
        "id": "p1", "name": "Fama-French 三因子", "type": "sys",
        "desc": "最经典的多因子模型，市场+规模+价值三大维度，解释股票收益的绝大部分变化",
        "src": "Fama & French 1993",
        "factors": [{"n": "市场因子", "w": 40}, {"n": "规模因子(SMB)", "w": 35}, {"n": "价值因子(HML)", "w": 25}],
        "detail": "全球最广泛引用的因子模型",
        "created_at": None,
    },
    {
        "id": "p2", "name": "Fama-French 五因子", "type": "sys",
        "desc": "在三因子基础上增加盈利因子(RMW)和投资因子(CMA)，解释能力更强",
        "src": "Fama & French 2015",
        "factors": [{"n": "市场因子", "w": 30}, {"n": "规模因子(SMB)", "w": 25}, {"n": "价值因子(HML)", "w": 20}, {"n": "盈利因子(RMW)", "w": 15}, {"n": "投资因子(CMA)", "w": 10}],
        "detail": "五因子模型将三因子的解释力从~70%提升至~85%",
        "created_at": None,
    },
    {
        "id": "p3", "name": "A股核心五因子", "type": "sys",
        "desc": "基于A股市场特征筛选的五个核心因子，市值加权LASSO选取得分最高组合",
        "src": "市值加权LASSO",
        "factors": [
            {"n": "20日动量", "w": 20}, {"n": "20日波动率", "w": 20}, {"n": "14日RSI", "w": 20},
            {"n": "5日量比", "w": 20}, {"n": "20日换手率", "w": 20},
        ],
        "detail": "覆盖动量、波动、超买超卖、量价四大维度",
        "created_at": None,
    },
    {
        "id": "p4", "name": "M8精选八因子", "type": "sys",
        "desc": "Jonathan Feng 2026年前沿因子研究，8个综合选股因子等权组合",
        "src": "Feng et al. 2026",
        "factors": [
            {"n": "截面动量", "w": 12.5}, {"n": "质量因子", "w": 12.5}, {"n": "低波因子", "w": 12.5},
            {"n": "价值因子", "w": 12.5}, {"n": "成长因子", "w": 12.5}, {"n": "情绪因子", "w": 12.5},
            {"n": "规模因子", "w": 12.5}, {"n": "投资因子", "w": 12.5},
        ],
        "detail": "八因子等权，适合作为多因子基准模型",
        "created_at": None,
    },
    {
        "id": "p5", "name": "短线动量", "type": "sys",
        "desc": "追强势选手的首选组合，动量+量价+超买信号三重确认",
        "src": "QuantsPlaybook",
        "factors": [{"n": "5日动量", "w": 30}, {"n": "14日RSI", "w": 25}, {"n": "5日量比", "w": 25}, {"n": "5日反转因子", "w": 20}],
        "detail": "适合短线（T+3~T+10）追强势股",
        "created_at": None,
    },
    {
        "id": "p6", "name": "价值防御", "type": "sys",
        "desc": "熊市抗跌组合，低估值+高质量+低波动+高股息+低杠杆",
        "src": "综合设计",
        "factors": [
            {"n": "市盈率倒数(EP)", "w": 30}, {"n": "ROE", "w": 20}, {"n": "20日波动率", "w": 20},
            {"n": "股息率", "w": 15}, {"n": "资产负债率", "w": 15},
        ],
        "detail": "防御性组合，适合震荡市或下跌行情",
        "created_at": None,
    },
    {
        "id": "p7", "name": "聪明钱因子组合", "type": "sys",
        "desc": "量化识别主力资金行为，跟踪聪明钱的选股信号",
        "src": "开源证券研报复现",
        "factors": [{"n": "大单净买入", "w": 30}, {"n": "资金流向强度", "w": 30}, {"n": "5日动量", "w": 25}, {"n": "量比", "w": 15}],
        "detail": "跟踪聪明钱信号，适合趋势确认后入场",
        "created_at": None,
    },
    {
        "id": "p8", "name": "量价核心", "type": "sys",
        "desc": "量与价两大维度的核心因子组合，系统现有能力的最佳整合",
        "src": "系统现有能力",
        "factors": [
            {"n": "5日动量", "w": 25}, {"n": "20日均线乖离率", "w": 20},
            {"n": "5日量比", "w": 25}, {"n": "20日换手率", "w": 15}, {"n": "20日波动率", "w": 15},
        ],
        "detail": "量价核心基础组合，适用于大部分市场环境",
        "created_at": None,
    },
    {
        "id": "p9", "name": "情绪感知", "type": "sys",
        "desc": "基于行为金融学的情绪状态因子合成组合，捕捉市场情绪极端",
        "src": "状态依赖因子合成",
        "factors": [
            {"n": "14日RSI", "w": 25}, {"n": "换手率变化", "w": 25},
            {"n": "5日动量", "w": 20}, {"n": "20日波动率", "w": 15}, {"n": "5日反转因子", "w": 15},
        ],
        "detail": "情绪极端时发出信号，适合逆向投资",
        "created_at": None,
    },
    {
        "id": "p10", "name": "基本面精选", "type": "sys",
        "desc": "财务指标为核心的基本面因子精选组合",
        "src": "quantitative_analysis",
        "factors": [
            {"n": "ROE", "w": 25}, {"n": "净利润增长率", "w": 25},
            {"n": "市盈率倒数(EP)", "w": 25}, {"n": "营收增长率", "w": 15}, {"n": "股息率", "w": 10},
        ],
        "detail": "适合中线持有（3~12个月）的稳健组合",
        "created_at": None,
    },
    {
        "id": "p11", "name": "ML Alpha 合成", "type": "sys",
        "desc": "基于机器学习的多因子Alpha合成策略，WorldQuant体系+QLib框架的融合",
        "src": "WorldQuant+ML",
        "factors": [{"n": "Alpha合成因子", "w": 60}, {"n": "深度学习因子", "w": 40}],
        "detail": "高收益高风险，适合风险承受能力较强的投资者",
        "created_at": None,
    },
    {
        "id": "p12", "name": "三因子+动量增强", "type": "sys",
        "desc": "Carhart四因子模型的A股扩展版，加入动量因子增强收益",
        "src": "Carhart四因子扩展",
        "factors": [
            {"n": "市场因子", "w": 30}, {"n": "规模因子(SMB)", "w": 25},
            {"n": "价值因子(HML)", "w": 20}, {"n": "动量因子(MOM)", "w": 25},
        ],
        "detail": "在经典三因子上增加动量维度，理论依据充分",
        "created_at": None,
    },
]


def _enrich_factor_info(info: dict, factor_id: int, category_factor_names: list = None):
    """
    将 BaseFactor.get_info() 输出映射到 219 规格书 §2.2 响应结构

    Args:
        info: BaseFactor.get_info() 返回的原始字典
        factor_id: 因子数字标识符（按名称排序）
        category_factor_names: 同分类所有因子名列表，用于生成 relate
    """
    examples_str = info.get("examples", "") or ""
    if isinstance(examples_str, str):
        examples_list = [e.strip() for e in examples_str.split("\n") if e.strip()]
    else:
        examples_list = examples_str if isinstance(examples_str, list) else []

    cat = info.get("category", "") or ""
    name = info.get("name", "") or ""

    # 自动生成关联因子：同分类中排除自身的前 4 个
    relate = list(info.get("relate", info.get("related_factors", [])))
    if not relate and category_factor_names and name:
        relate = [fn for fn in category_factor_names if fn != name][:4]

    enriched = {
        "id": factor_id,
        "name": name,
        "cn": info.get("name_cn", "") or "",
        "cat": cat,
        "catCN": CATEGORY_CN_MAP.get(cat, {}).get("cn", cat),
        "src": info.get("source", "") or "",
        "desc": info.get("description", "") or "",
        "tags": info.get("tags", {}),
        "params": info.get("params", []),
        "examples": examples_list,
        "relate": relate,
        # 保留原始字段保证向后兼容
        "name_cn": info.get("name_cn", "") or "",
        "subcategory": info.get("subcategory", "") or "",
        "formula": info.get("formula", "") or "",
        "source_detail": info.get("source_detail", "") or "",
        "required_columns": info.get("required_columns", []),
    }
    return enriched


def _build_factor_id_map():
    """为所有因子分配稳定的数字 ID（按名称字母序）"""
    all_names = sorted(registry.list_factors())
    return {name: idx + 1 for idx, name in enumerate(all_names)}


def _get_category_factor_names():
    """获取每个分类下的因子名列表"""
    result = {}
    for cat in registry.list_categories():
        if cat:
            result[cat] = [fn for fn in registry.get_category_factors(cat) if fn]
    return result


# ══════════════════════════════════════════════════════════════
# 因子 CRUD 端点
# ══════════════════════════════════════════════════════════════


@factors_bp.route('', methods=['GET'])
@handle_exceptions
def get_all_factors():
    """
    获取所有因子列表（219 规格书 §2.2）
    支持按类别、来源、关键词筛选
    返回 219 规格书对齐的结构：id/cn/cat/catCN/src/desc/tags/params/examples/relate
    """
    category = request.args.get('category')
    source = request.args.get('source')
    search = request.args.get('search')

    if search:
        factor_names = registry.search_factors(search)
    else:
        factor_names = registry.list_factors(category=category, source=source)

    factor_id_map = _build_factor_id_map()
    cat_factor_names = _get_category_factor_names()

    factors_info = []
    for name in factor_names:
        if not name:
            continue  # 跳过空名称因子
        factor = registry.get_factor(name)
        if factor:
            info = factor.get_info()
            cat = info.get("category", "") or ""
            enriched = _enrich_factor_info(
                info,
                factor_id_map.get(name, 0),
                cat_factor_names.get(cat),
            )
            factors_info.append(enriched)

    return jsonify({
        'success': True,
        'data': factors_info,
        'total': len(factors_info),
    })


@factors_bp.route('/categories', methods=['GET'])
@handle_exceptions
def get_categories():
    """
    获取所有因子分类及计数（219 规格书 §2.3）

    返回结构：{key, cn, count} — cn 为中文名+emoji
    仅返回有因子的分类（跳过空分类和空名称分类）
    """
    registry_cats = [c for c in registry.list_categories() if c]
    category_info = []

    for cat in registry_cats:
        count = len([fn for fn in registry.get_category_factors(cat) if fn])
        if count == 0:
            continue
        cn_entry = CATEGORY_CN_MAP.get(cat, {})
        category_info.append({
            "key": cat,
            "cn": cn_entry.get("cn", cat),
            "order": cn_entry.get("order", 99),
            "count": count,
        })

    # 按 order 排序
    category_info.sort(key=lambda x: x["order"])

    return jsonify({
        'success': True,
        'data': category_info,
    })


@factors_bp.route('/sources', methods=['GET'])
@handle_exceptions
def get_sources():
    """
    获取所有来源
    """
    sources = registry.list_sources()
    source_info = []

    for src in sources:
        count = len(registry.get_source_factors(src))
        source_info.append({
            'name': src,
            'count': count
        })

    return jsonify({
        'success': True,
        'data': source_info
    })


@factors_bp.route('/<factor_name>', methods=['GET'])
@handle_exceptions
def get_factor_detail(factor_name):
    """
    获取单个因子详情（219 规格书 §2.4）
    返回 enriched 结构，增加 usage_notes 字段
    """
    factor = registry.get_factor(factor_name)

    if factor is None:
        return jsonify({
            'success': False,
            'error': f'因子 {factor_name} 不存在',
            'error_type': 'FactorNotFound',
        }), 404

    info = factor.get_info()
    factor_id_map = _build_factor_id_map()
    cat_factor_names = _get_category_factor_names()
    cat = info.get("category", "") or ""

    enriched = _enrich_factor_info(
        info,
        factor_id_map.get(factor_name, 0),
        cat_factor_names.get(cat),
    )

    # 添加 usage_notes（219 §2.4 额外字段）
    enriched["usage_notes"] = f"{info.get('name_cn', factor_name)}是{info.get('description', '')}。适用于{cat}策略。"

    return jsonify({
        'success': True,
        'data': enriched,
    })


@factors_bp.route('/calculate/<factor_name>', methods=['POST'])
@handle_exceptions
def calculate_single_factor(factor_name):
    """
    计算单个因子
    """
    data = request.json
    df = pd.DataFrame(data.get('data', [])) if data else pd.DataFrame()
    params = data.get('params', {}) if data else {}

    factor_series = calculator.calculate_single_factor(df, factor_name, **params)

    if factor_series is None:
        return jsonify({
            'success': False,
            'error': '因子计算失败',
            'error_type': 'FactorCalculationFailed',
        }), 400

    result = factor_series.reset_index()
    result.columns = ['trade_date', 'value']

    return jsonify({
        'success': True,
        'data': result.to_dict(orient='records'),
    })


@factors_bp.route('/calculate-combination', methods=['POST'])
@handle_exceptions
def calculate_combination():
    """
    计算因子组合
    """
    data = request.json
    df = pd.DataFrame(data.get('data', [])) if data else pd.DataFrame()
    factors_config = data.get('factors', []) if data else []

    result_df = calculator.calculate_multiple_factors(df, factors_config)

    if result_df.empty:
        return jsonify({
            'success': False,
            'error': '因子组合计算失败',
            'error_type': 'CombinationCalculationFailed',
        }), 400

    result = result_df.reset_index()

    return jsonify({
        'success': True,
        'data': result.to_dict(orient='records'),
        'columns': list(result_df.columns),
    })


@factors_bp.route('/evaluate', methods=['POST'])
@handle_exceptions
def evaluate_factors():
    """
    评估因子质量
    计算IC、IR、换手率等指标
    """
    data = request.json
    factors_df = pd.DataFrame(data.get('factors_data', [])) if data else pd.DataFrame()
    price_df = pd.DataFrame(data.get('price_data', [])) if data else pd.DataFrame()
    periods = data.get('periods', [1, 5, 10]) if data else [1, 5, 10]

    if factors_df.empty or price_df.empty:
        return jsonify({
            'success': False,
            'error': '数据不能为空',
            'error_type': 'ValidationError',
        }), 400

    results = evaluator.evaluate_multiple_factors(factors_df, price_df, periods)

    return jsonify({
        'success': True,
        'data': results,
    })


@factors_bp.route('/combinations', methods=['GET'])
@handle_exceptions
def get_combinations():
    """
    获取因子组合列表（219 规格书 §2.5）
    系统预设 + 用户自建组合合并返回

    Query params:
        type: all（默认）| sys | user
    """
    filter_type = request.args.get('type', 'all')

    # 系统预设组合
    presets = list(PRESET_COMBOS) if filter_type in ('all', 'sys') else []

    # 用户自建组合
    user_combos = []
    if filter_type in ('all', 'user'):
        db_path = get_db_path()
        _ensure_combo_db()
        conn = _get_combo_conn()
        try:
            cursor = conn.cursor()
            cursor.execute(
                """SELECT id, name, description, factors, src, detail, created_at
                   FROM factor_combinations
                   WHERE type = 'user'
                   ORDER BY created_at DESC"""
            )
            rows = cursor.fetchall()
            for row in rows:
                try:
                    factors = json.loads(row[3]) if row[3] else []
                except Exception:
                    factors = []

                # 将用户组合的 factors 转换为 {n, w} 格式
                mapped_factors = []
                for f in factors:
                    if isinstance(f, dict):
                        mapped_factors.append({
                            "n": f.get("n", f.get("name", f.get("factor_name", ""))),
                            "w": f.get("w", f.get("weight", f.get("factor_weight", 0))),
                        })
                    else:
                        mapped_factors.append({"n": str(f), "w": 0})

                user_combos.append({
                    "id": f"u{row[0]}",
                    "name": row[1],
                    "type": "user",
                    "desc": row[2] or "",
                    "src": row[4] or "用户自建",
                    "factors": mapped_factors,
                    "detail": row[5] or None,
                    "created_at": row[6],
                })
        except Exception as e:
            logger.warning(f"读取用户组合失败: {e}")
        finally:
                conn.close()

    all_combos = presets + user_combos

    return jsonify({
        'success': True,
        'data': all_combos,
    })


@factors_bp.route('/combinations', methods=['POST'])
@handle_exceptions
def save_combination():
    """
    保存因子组合（219 规格书 §2.6）
    """
    data = request.json
    name = data.get('name')
    description = data.get('desc', '')
    factors = data.get('factors', [])
    src = data.get('src', '用户自建')

    if not name:
        return jsonify({'success': False, 'error': '组合名称不能为空', 'error_type': 'ValidationError'}), 400
    if not factors:
        return jsonify({'success': False, 'error': '请至少选择1个因子', 'error_type': 'NoFactorsSelected'}), 400

    # 检查权重合计
    weight_total = sum(f.get('w', f.get('weight', 0)) for f in factors)
    if weight_total and abs(weight_total - 100) > 1:
        return jsonify({
            'success': False,
            'error': '权重合计需等于100%',
            'error_type': 'InvalidWeights',
            'current_total': weight_total,
        }), 400

    # 构建存储用的 factors 结构
    stored_factors = []
    for f in factors:
        if isinstance(f, dict):
            stored_factors.append({
                "name": f.get("n", f.get("name", "")),
                "weight": f.get("w", f.get("weight", 0)),
            })
        else:
            stored_factors.append({"name": str(f), "weight": 0})

    db_path = get_db_path()
    _ensure_combo_db()

    conn = _get_combo_conn()
    try:
        cursor = conn.cursor()
        cursor.execute(
            """INSERT INTO factor_combinations (name, description, factors, type, src)
               VALUES (?, ?, ?, 'user', ?)""",
            (name, description, json.dumps(stored_factors), src)
        )
        conn.commit()
        combo_id = cursor.lastrowid

        return jsonify({
            'success': True,
            'data': {
                'id': f"u{combo_id}",
                'name': name,
                'type': 'user',
                'desc': description,
                'src': src,
                'factors': [{"n": f["name"], "w": f["weight"]} for f in stored_factors],
                'detail': None,
                'created_at': datetime.now().isoformat(),
            }
        }), 201
    finally:
        conn.close()


@factors_bp.route('/combinations/<int:combo_id>', methods=['PUT'])
@handle_exceptions
def update_combination(combo_id):
    """
    更新因子组合（219 规格书 §2.7）
    name/desc/factors/src 均为可选字段（部分更新）
    """
    data = request.json
    name = data.get('name')
    description = data.get('desc')
    factors = data.get('factors')
    src = data.get('src')

    _ensure_combo_db()

    conn = _get_combo_conn()
    try:
        cursor = conn.cursor()
        update_fields = []
        update_values = []

        if name is not None:
            update_fields.append("name = ?")
            update_values.append(name)
        if description is not None:
            update_fields.append("description = ?")
            update_values.append(description)
        if src is not None:
            update_fields.append("src = ?")
            update_values.append(src)
        if factors is not None:
            stored_factors = []
            for f in factors:
                if isinstance(f, dict):
                    stored_factors.append({
                        "name": f.get("n", f.get("name", "")),
                        "weight": f.get("w", f.get("weight", 0)),
                    })
                else:
                    stored_factors.append({"name": str(f), "weight": 0})
            update_fields.append("factors = ?")
            update_values.append(json.dumps(stored_factors))

        if update_fields:
            update_fields.append("updated_at = CURRENT_TIMESTAMP")
            update_values.append(combo_id)
            cursor.execute(
                f"UPDATE factor_combinations SET {', '.join(update_fields)} WHERE id = ? AND type = 'user'",
                update_values
            )
            conn.commit()

        if cursor.rowcount == 0:
            return jsonify({
                'success': False,
                'error': '组合不存在或为系统预设',
                'error_type': 'ComboNotFound',
            }), 404

        return jsonify({'success': True, 'data': {'updated': True}})
    finally:
        conn.close()


@factors_bp.route('/combinations/<int:combo_id>', methods=['DELETE'])
@handle_exceptions
def delete_combination(combo_id):
    """
    删除因子组合（219 规格书 §2.7）
    仅可删除用户自建组合，系统预设不可删除
    """
    _ensure_combo_db()
    conn = _get_combo_conn()
    try:
        cursor = conn.cursor()
        cursor.execute("DELETE FROM factor_combinations WHERE id = ? AND type = 'user'", (combo_id,))
        conn.commit()

        if cursor.rowcount == 0:
            return jsonify({
                'success': False,
                'error': '组合不存在或不可删除（系统预设）',
                'error_type': 'ComboNotFound',
            }), 404

        return jsonify({'success': True, 'data': {'deleted': True}})
    finally:
        conn.close()


@factors_bp.route('/combinations/<int:combo_id>/set-default', methods=['POST'])
@handle_exceptions
def set_default_combination(combo_id):
    """
    设置默认组合
    仅可对用户自建组合操作
    """
    _ensure_combo_db()
    conn = _get_combo_conn()
    try:
        cursor = conn.cursor()
        cursor.execute("UPDATE factor_combinations SET is_default = 0 WHERE type = 'user'")
        cursor.execute("UPDATE factor_combinations SET is_default = 1 WHERE id = ? AND type = 'user'", (combo_id,))
        conn.commit()
        return jsonify({'success': True, 'data': {'defaulted': cursor.rowcount > 0}})
    finally:
        conn.close()


@factors_bp.route('/precompute', methods=['POST'])
@handle_exceptions
def precompute_factors():
    """
    预计算因子
    批量计算并缓存因子数据
    """
    data = request.json
    ts_code = data.get('ts_code') if data else None
    df_data = data.get('data', []) if data else []
    factor_names = data.get('factors') if data else None

    if not ts_code or not df_data:
        return jsonify({
            'success': False,
            'error': '缺少必要参数',
            'error_type': 'ValidationError',
        }), 400

    df = pd.DataFrame(df_data)

    if factor_names:
        results = {}
        for name in factor_names:
            success = precompute_manager.precompute_factor(ts_code, df, name)
            results[name] = success
    else:
        results = precompute_manager.precompute_all_factors(ts_code, df)

    success_count = sum(1 for v in results.values() if v)

    return jsonify({
        'success': True,
        'data': {
            'total': len(results),
            'success': success_count,
            'failed': len(results) - success_count,
            'results': results,
        },
    })


@factors_bp.route('/backtest', methods=['POST'])
@handle_exceptions
def backtest_combination():
    """
    因子组合回测
    计算绩效指标
    """
    data = request.json
    price_data = pd.DataFrame(data.get('price_data', [])) if data else pd.DataFrame()
    benchmark_data = data.get('benchmark_data') if data else None
    initial_capital = data.get('initial_capital', 100000) if data else 100000

    if price_data.empty:
        return jsonify({
            'success': False,
            'error': '价格数据不能为空',
            'error_type': 'ValidationError',
        }), 400

    if 'trade_date' in price_data.columns:
        price_data = price_data.set_index('trade_date')

    benchmark_df = None
    if benchmark_data:
        benchmark_df = pd.DataFrame(benchmark_data)
        if 'trade_date' in benchmark_df.columns:
            benchmark_df = benchmark_df.set_index('trade_date')

    engine = BacktestEngine(initial_capital=initial_capital)
    result = engine.run_simple_backtest(price_data, benchmark_data=benchmark_df)

    return jsonify({
        'success': True,
        'data': result.to_dict(),
    })


@factors_bp.route('/strategies', methods=['GET'])
@handle_exceptions
def list_strategies():
    """
    获取可用策略列表
    """
    pipeline = get_strategy_pipeline()
    available = pipeline.get_available_strategies()
    active = pipeline.list_strategies()

    return jsonify({
        'success': True,
        'data': {
            'available': available,
            'active': active,
        },
    })


@factors_bp.route('/strategies/pipeline/screen', methods=['POST'])
@handle_exceptions
def run_strategy_screen():
    """
    运行策略筛选
    """
    data = request.json
    price_data = pd.DataFrame(data.get('price_data', [])) if data else pd.DataFrame()

    if price_data.empty:
        return jsonify({
            'success': False,
            'error': '价格数据不能为空',
            'error_type': 'ValidationError',
        }), 400

    if 'trade_date' in price_data.columns:
        price_data = price_data.set_index('trade_date')

    pipeline = get_strategy_pipeline()
    signals = pipeline.generate_combined_signals(price_data)

    return jsonify({
        'success': True,
        'data': {
            'signals': signals.to_dict() if not signals.empty else {},
            'message': '策略信号生成完成（当前为预留框架，实际策略待实现）',
        },
    })
