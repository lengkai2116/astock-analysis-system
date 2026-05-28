"""
策略模板系统API路由
提供策略模板的CRUD操作
"""
from flask import Blueprint, request, jsonify
import sqlite3
import json
from datetime import datetime
import logging
from app.utils.error_handlers import handle_exceptions

strategy_templates_bp = Blueprint('strategy_templates', __name__, url_prefix='/api/strategy-templates')
logger = logging.getLogger(__name__)

DB_PATH = 'strategy_templates.db'

def get_db_path():
    import os
    base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    return os.path.join(base_dir, '..', DB_PATH)

def init_db():
    conn = sqlite3.connect(get_db_path())
    cursor = conn.cursor()
    
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS strategy_templates (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            description TEXT,
            category TEXT NOT NULL,
            code_template TEXT NOT NULL,
            parameters TEXT,
            is_system BOOLEAN DEFAULT 0,
            author_id INTEGER,
            rating REAL DEFAULT 0.0,
            usage_count INTEGER DEFAULT 0,
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
            updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
        )
    ''')
    
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS template_parameters (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            template_id INTEGER NOT NULL,
            name TEXT NOT NULL,
            type TEXT NOT NULL,
            default_value TEXT,
            min_value REAL,
            max_value REAL,
            step REAL,
            description TEXT,
            FOREIGN KEY (template_id) REFERENCES strategy_templates(id)
        )
    ''')
    
    # 插入预置策略模板
    init_system_templates(cursor)
    
    conn.commit()
    conn.close()

def init_system_templates(cursor):
    """初始化系统预置策略模板"""
    
    templates = [
        {
            "name": "移动平均线策略",
            "description": "使用短期和长期移动平均线的交叉来判断趋势",
            "category": "trend_following",
            "code_template": '''
def initialize(context):
    """初始化策略参数"""
    context.short_ma = {{MA_SHORT}}
    context.long_ma = {{MA_LONG}}
    context.position_size = {{POSITION_SIZE}}
    
def handle_bar(context, bar):
    """处理每个K线"""
    short_ma = bar.close[-context.short_ma:].mean()
    long_ma = bar.close[-context.long_ma:].mean()
    
    position = context.portfolio.position
    
    if short_ma > long_ma and position == 0:
        context.buy(context.stock, context.position_size)
    elif short_ma < long_ma and position > 0:
        context.sell(context.stock, position)
''',
            "parameters": [
                {"name": "MA_SHORT", "type": "int", "default_value": "5", "min_value": 1, "max_value": 100, "description": "短期均线周期"},
                {"name": "MA_LONG", "type": "int", "default_value": "20", "min_value": 5, "max_value": 200, "description": "长期均线周期"},
                {"name": "POSITION_SIZE", "type": "int", "default_value": "100", "min_value": 1, "max_value": 10000, "description": "每次交易数量"}
            ]
        },
        {
            "name": "RSI均值回归策略",
            "description": "使用RSI指标识别超买超卖信号",
            "category": "mean_reversion",
            "code_template": '''
import numpy as np

def initialize(context):
    """初始化策略参数"""
    context.rsi_period = {{RSI_PERIOD}}
    context.rsi_oversold = {{RSI_OVERSOLD}}
    context.rsi_overbought = {{RSI_OVERBOUGHT}}
    context.position_size = {{POSITION_SIZE}}
    
def calculate_rsi(prices, period):
    """计算RSI指标"""
    deltas = np.diff(prices)
    gains = np.where(deltas > 0, deltas, 0)
    losses = np.where(deltas < 0, -deltas, 0)
    
    avg_gain = gains[-period:].mean()
    avg_loss = losses[-period:].mean()
    
    if avg_loss == 0:
        return 100
    
    rs = avg_gain / avg_loss
    rsi = 100 - (100 / (1 + rs))
    return rsi

def handle_bar(context, bar):
    """处理每个K线"""
    rsi = calculate_rsi(bar.close, context.rsi_period)
    
    position = context.portfolio.position
    
    if rsi < context.rsi_oversold and position == 0:
        context.buy(context.stock, context.position_size)
    elif rsi > context.rsi_overbought and position > 0:
        context.sell(context.stock, position)
''',
            "parameters": [
                {"name": "RSI_PERIOD", "type": "int", "default_value": "14", "min_value": 2, "max_value": 50, "description": "RSI计算周期"},
                {"name": "RSI_OVERSOLD", "type": "int", "default_value": "30", "min_value": 10, "max_value": 50, "description": "超卖阈值"},
                {"name": "RSI_OVERBOUGHT", "type": "int", "default_value": "70", "min_value": 50, "max_value": 90, "description": "超买阈值"},
                {"name": "POSITION_SIZE", "type": "int", "default_value": "100", "min_value": 1, "max_value": 10000, "description": "每次交易数量"}
            ]
        },
        {
            "name": "布林带策略",
            "description": "使用布林带突破策略",
            "category": "trend_following",
            "code_template": '''
import numpy as np

def initialize(context):
    """初始化策略参数"""
    context.bollinger_period = {{BOLLINGER_PERIOD}}
    context.bollinger_std = {{BOLLINGER_STD}}
    context.position_size = {{POSITION_SIZE}}
    
def handle_bar(context, bar):
    """处理每个K线"""
    prices = bar.close[-context.bollinger_period:]
    sma = prices.mean()
    std = prices.std()
    
    upper_band = sma + (std * context.bollinger_std)
    lower_band = sma - (std * context.bollinger_std)
    
    current_price = bar.close[-1]
    position = context.portfolio.position
    
    if current_price > upper_band and position == 0:
        context.buy(context.stock, context.position_size)
    elif current_price < lower_band and position > 0:
        context.sell(context.stock, position)
''',
            "parameters": [
                {"name": "BOLLINGER_PERIOD", "type": "int", "default_value": "20", "min_value": 5, "max_value": 100, "description": "布林带计算周期"},
                {"name": "BOLLINGER_STD", "type": "float", "default_value": "2.0", "min_value": 0.5, "max_value": 5.0, "step": 0.5, "description": "标准差倍数"},
                {"name": "POSITION_SIZE", "type": "int", "default_value": "100", "min_value": 1, "max_value": 10000, "description": "每次交易数量"}
            ]
        },
        {
            "name": "MACD策略",
            "description": "使用MACD指标进行趋势判断",
            "category": "trend_following",
            "code_template": '''
import numpy as np

def initialize(context):
    """初始化策略参数"""
    context.fast_period = {{FAST_PERIOD}}
    context.slow_period = {{SLOW_PERIOD}}
    context.signal_period = {{SIGNAL_PERIOD}}
    context.position_size = {{POSITION_SIZE}}
    
def calculate_ema(prices, period):
    """计算指数移动平均"""
    weights = np.exp(np.linspace(-1., 0., period))
    weights /= weights.sum()
    return np.convolve(prices, weights, mode='valid')[-1]

def handle_bar(context, bar):
    """处理每个K线"""
    fast_ema = calculate_ema(bar.close[-context.fast_period-10:], context.fast_period)
    slow_ema = calculate_ema(bar.close[-context.slow_period-10:], context.slow_period)
    macd = fast_ema - slow_ema
    signal = calculate_ema(np.array([macd] * (context.signal_period + 10)), context.signal_period)
    
    position = context.portfolio.position
    
    if macd > signal and position == 0:
        context.buy(context.stock, context.position_size)
    elif macd < signal and position > 0:
        context.sell(context.stock, position)
''',
            "parameters": [
                {"name": "FAST_PERIOD", "type": "int", "default_value": "12", "min_value": 2, "max_value": 50, "description": "快线周期"},
                {"name": "SLOW_PERIOD", "type": "int", "default_value": "26", "min_value": 5, "max_value": 100, "description": "慢线周期"},
                {"name": "SIGNAL_PERIOD", "type": "int", "default_value": "9", "min_value": 2, "max_value": 30, "description": "信号线周期"},
                {"name": "POSITION_SIZE", "type": "int", "default_value": "100", "min_value": 1, "max_value": 10000, "description": "每次交易数量"}
            ]
        },
        {
            "name": "KD随机指标策略",
            "description": "使用KDJ指标进行超买超卖判断",
            "category": "mean_reversion",
            "code_template": '''
import numpy as np

def initialize(context):
    """初始化策略参数"""
    context.kdj_period = {{KDJ_PERIOD}}
    context.kd_signal_period = {{KD_SIGNAL_PERIOD}}
    context.k_oversold = {{K_OVERSOLD}}
    context.k_overbought = {{K_OVERBOUGHT}}
    context.position_size = {{POSITION_SIZE}}
    
def calculate_kdj(high, low, close, period):
    """计算KDJ指标"""
    lowest_low = np.min(low[-period:])
    highest_high = np.max(high[-period:])
    
    rsv = (close[-1] - lowest_low) / (highest_high - lowest_low) * 100
    return rsv

def handle_bar(context, bar):
    """处理每个K线"""
    rsv = calculate_kdj(bar.high, bar.low, bar.close, context.kdj_period)
    k = 50 if rsv == 0 else rsv
    
    position = context.portfolio.position
    
    if k < context.k_oversold and position == 0:
        context.buy(context.stock, context.position_size)
    elif k > context.k_overbought and position > 0:
        context.sell(context.stock, position)
''',
            "parameters": [
                {"name": "KDJ_PERIOD", "type": "int", "default_value": "9", "min_value": 3, "max_value": 30, "description": "KDJ计算周期"},
                {"name": "KD_SIGNAL_PERIOD", "type": "int", "default_value": "3", "min_value": 2, "max_value": 10, "description": "KD信号周期"},
                {"name": "K_OVERSOLD", "type": "int", "default_value": "20", "min_value": 5, "max_value": 40, "description": "K线超卖阈值"},
                {"name": "K_OVERBOUGHT", "type": "int", "default_value": "80", "min_value": 60, "max_value": 95, "description": "K线超买阈值"},
                {"name": "POSITION_SIZE", "type": "int", "default_value": "100", "min_value": 1, "max_value": 10000, "description": "每次交易数量"}
            ]
        }
    ]
    
    for template in templates:
        cursor.execute('''
            INSERT OR IGNORE INTO strategy_templates 
            (name, description, category, code_template, parameters, is_system)
            VALUES (?, ?, ?, ?, ?, 1)
        ''', (
            template["name"],
            template["description"],
            template["category"],
            template["code_template"],
            json.dumps(template["parameters"])
        ))

# 初始化数据库
init_db()

@strategy_templates_bp.route('', methods=['GET'])
@handle_exceptions
def get_templates():
    """获取策略模板列表"""
    page = request.args.get('page', 1, type=int)
    page_size = request.args.get('page_size', 20, type=int)
    category = request.args.get('category')
    search = request.args.get('search')
    
    conn = sqlite3.connect(get_db_path())
    cursor = conn.cursor()
    
    query = "SELECT * FROM strategy_templates WHERE 1=1"
    params = []
    
    if category:
        query += " AND category = ?"
        params.append(category)
    
    if search:
        query += " AND (name LIKE ? OR description LIKE ?)"
        params.extend([f"%{search}%", f"%{search}%"])
    
    # 获取总数
    count_query = query.replace("SELECT *", "SELECT COUNT(*)")
    cursor.execute(count_query, params)
    total = cursor.fetchone()[0]
    
    # 获取分页数据
    offset = (page - 1) * page_size
    query += " ORDER BY usage_count DESC, rating DESC LIMIT ? OFFSET ?"
    params.extend([page_size, offset])
    
    cursor.execute(query, params)
    rows = cursor.fetchall()
    
    templates = []
    for row in rows:
        templates.append({
            "id": row[0],
            "name": row[1],
            "description": row[2],
            "category": row[3],
            "code_template": row[4],
            "parameters": json.loads(row[5]) if row[5] else [],
            "is_system": bool(row[6]),
            "author_id": row[7],
            "rating": row[8],
            "usage_count": row[9],
            "created_at": row[10],
            "updated_at": row[11]
        })
    
    conn.close()
    
    return jsonify({
        "success": True,
        "data": templates,
        "total": total,
        "page": page,
        "page_size": page_size
    })

@strategy_templates_bp.route('/categories', methods=['GET'])
@handle_exceptions
def get_categories():
    """获取策略模板分类列表"""
    categories = [
        {"id": "trend_following", "name": "趋势跟踪", "icon": "📈"},
        {"id": "mean_reversion", "name": "均值回归", "icon": "📉"},
        {"id": "arbitrage", "name": "套利", "icon": "⚖️"},
        {"id": "event_driven", "name": "事件驱动", "icon": "📰"},
        {"id": "custom", "name": "自定义", "icon": "🎯"}
    ]
    
    return jsonify({
        "success": True,
        "data": categories
    })

@strategy_templates_bp.route('/<int:template_id>', methods=['GET'])
@handle_exceptions
def get_template(template_id):
    """获取单个策略模板详情"""
    conn = sqlite3.connect(get_db_path())
    cursor = conn.cursor()
    
    cursor.execute("SELECT * FROM strategy_templates WHERE id = ?", (template_id,))
    row = cursor.fetchone()
    
    if not row:
        conn.close()
        return jsonify({
            "success": False,
            "message": "策略模板不存在"
        }), 404
    
    template = {
        "id": row[0],
        "name": row[1],
        "description": row[2],
        "category": row[3],
        "code_template": row[4],
        "parameters": json.loads(row[5]) if row[5] else [],
        "is_system": bool(row[6]),
        "author_id": row[7],
        "rating": row[8],
        "usage_count": row[9],
        "created_at": row[10],
        "updated_at": row[11]
    }
    
    # 更新使用次数
    cursor.execute(
        "UPDATE strategy_templates SET usage_count = usage_count + 1 WHERE id = ?",
        (template_id,)
    )
    conn.commit()
    conn.close()
    
    return jsonify({
        "success": True,
        "data": template
    })

@strategy_templates_bp.route('', methods=['POST'])
@handle_exceptions
def create_template():
    """创建新的策略模板"""
    data = request.json
    
    name = data.get('name')
    description = data.get('description')
    category = data.get('category')
    code_template = data.get('code_template')
    parameters = data.get('parameters', [])
    
    if not name or not category or not code_template:
        return jsonify({
            "success": False,
            "message": "名称、分类和代码模板为必填项"
        }), 400
    
    conn = sqlite3.connect(get_db_path())
    cursor = conn.cursor()
    
    cursor.execute('''
        INSERT INTO strategy_templates 
        (name, description, category, code_template, parameters, is_system)
        VALUES (?, ?, ?, ?, ?, 0)
    ''', (name, description, category, code_template, json.dumps(parameters)))
    
    template_id = cursor.lastrowid
    conn.commit()
    conn.close()
    
    return jsonify({
        "success": True,
        "data": {"id": template_id},
        "message": "策略模板创建成功"
    })

@strategy_templates_bp.route('/<int:template_id>', methods=['PUT'])
@handle_exceptions
def update_template(template_id):
    """更新策略模板"""
    data = request.json
    
    name = data.get('name')
    description = data.get('description')
    category = data.get('category')
    code_template = data.get('code_template')
    parameters = data.get('parameters')
    
    conn = sqlite3.connect(get_db_path())
    cursor = conn.cursor()
    
    update_fields = []
    update_values = []
    
    if name is not None:
        update_fields.append("name = ?")
        update_values.append(name)
    if description is not None:
        update_fields.append("description = ?")
        update_values.append(description)
    if category is not None:
        update_fields.append("category = ?")
        update_values.append(category)
    if code_template is not None:
        update_fields.append("code_template = ?")
        update_values.append(code_template)
    if parameters is not None:
        update_fields.append("parameters = ?")
        update_values.append(json.dumps(parameters))
    
    if update_fields:
        update_fields.append("updated_at = CURRENT_TIMESTAMP")
        update_values.append(template_id)
        cursor.execute(f'''
            UPDATE strategy_templates 
            SET {', '.join(update_fields)} 
            WHERE id = ?
        ''', update_values)
        conn.commit()
    
    conn.close()
    
    return jsonify({
        "success": True,
        "message": "策略模板更新成功"
    })

@strategy_templates_bp.route('/<int:template_id>', methods=['DELETE'])
@handle_exceptions
def delete_template(template_id):
    """删除策略模板"""
    conn = sqlite3.connect(get_db_path())
    cursor = conn.cursor()
    
    # 检查是否为系统模板
    cursor.execute("SELECT is_system FROM strategy_templates WHERE id = ?", (template_id,))
    row = cursor.fetchone()
    
    if not row:
        conn.close()
        return jsonify({
            "success": False,
            "message": "策略模板不存在"
        }), 404
    
    if bool(row[0]):
        conn.close()
        return jsonify({
            "success": False,
            "message": "系统预置模板不能删除"
        }), 403
    
    cursor.execute("DELETE FROM strategy_templates WHERE id = ?", (template_id,))
    conn.commit()
    conn.close()
    
    return jsonify({
        "success": True,
        "message": "策略模板删除成功"
    })
