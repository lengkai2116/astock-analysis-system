from app import db
from app.models.strategy import StrategyTemplateV2, StrategyTemplateType
from app.services.strategy_template_service import StrategyTemplateService

SYSTEM_TEMPLATES = [
    {
        'name': '均线交叉策略',
        'description': '基于短期和长期均线的交叉产生交易信号，适用于趋势跟踪',
        'template_type': 'indicator',
        'code_template': '''my_strategy_name = "均线交叉策略"
my_strategy_description = "基于短期和长期均线的交叉产生交易信号，适用于趋势跟踪"

# @param short_period int 5 短期均线周期
# @param long_period int 20 长期均线周期
# @param position_pct float 0.3 仓位比例

import numpy as np

def initialize(context):
    context.short_period = short_period
    context.long_period = long_period
    context.position_pct = position_pct

def handle_data(context, data):
    stock = context.security
    
    short_ma = data[stock].mavg(short_period, field='close')
    long_ma = data[stock].mavg(long_period, field='close')
    
    if short_ma > long_ma and context.portfolio.positions[stock].amount == 0:
        order_target_percent(stock, context.position_pct)
    elif short_ma < long_ma and context.portfolio.positions[stock].amount > 0:
        order_target_percent(stock, 0)

def output_schema():
    return {
        "signal": "bullish/bearish",
        "confidence": 0.0-1.0,
        "entry_zone": [entry_low, entry_high],
        "risk_line": stop_loss,
        "target_zone": [target_low, target_high],
        "evidence": ["短期均线上穿长期均线", "量能放大"]
    }
''',
        'parameters': [
            {'name': 'short_period', 'type': 'int', 'default': '5', 'description': '短期均线周期'},
            {'name': 'long_period', 'type': 'int', 'default': '20', 'description': '长期均线周期'},
            {'name': 'position_pct', 'type': 'float', 'default': '0.3', 'description': '仓位比例'}
        ],
        'author': 'System',
        'is_system': True
    },
    {
        'name': 'MACD策略',
        'description': '使用MACD指标的背离和交叉信号进行交易判断',
        'template_type': 'indicator',
        'code_template': '''my_strategy_name = "MACD策略"
my_strategy_description = "使用MACD指标的背离和交叉信号进行交易判断"

# @param fast_period int 12 快线周期
# @param slow_period int 26 慢线周期
# @param signal_period int 9 信号线周期
# @param position_pct float 0.25 仓位比例

def initialize(context):
    context.fast_period = fast_period
    context.slow_period = slow_period
    context.signal_period = signal_period
    context.position_pct = position_pct

def handle_data(context, data):
    stock = context.security
    
    macd, signal, hist = data[stock].macd(
        fast_period, slow_period, signal_period, field='close'
    )
    
    if hist > 0 and context.portfolio.positions[stock].amount == 0:
        order_target_percent(stock, context.position_pct)
    elif hist < 0 and context.portfolio.positions[stock].amount > 0:
        order_target_percent(stock, 0)

def output_schema():
    return {
        "signal": "bullish/bearish",
        "confidence": 0.0-1.0,
        "entry_zone": [entry_low, entry_high],
        "risk_line": stop_loss,
        "target_zone": [target_low, target_high],
        "evidence": ["MACD金叉/死叉", "柱状图放大/缩小"]
    }
''',
        'parameters': [
            {'name': 'fast_period', 'type': 'int', 'default': '12', 'description': '快线周期'},
            {'name': 'slow_period', 'type': 'int', 'default': '26', 'description': '慢线周期'},
            {'name': 'signal_period', 'type': 'int', 'default': '9', 'description': '信号线周期'},
            {'name': 'position_pct', 'type': 'float', 'default': '0.25', 'description': '仓位比例'}
        ],
        'author': 'System',
        'is_system': True
    },
    {
        'name': 'RSI超买超卖策略',
        'description': '基于RSI指标判断市场超买超卖状态，把握反转机会',
        'template_type': 'indicator',
        'code_template': '''my_strategy_name = "RSI超买超卖策略"
my_strategy_description = "基于RSI指标判断市场超买超卖状态，把握反转机会"

# @param rsi_period int 14 RSI计算周期
# @param oversold_level float 30 超卖阈值
# @param overbought_level float 70 超买阈值
# @param position_pct float 0.2 仓位比例

def initialize(context):
    context.rsi_period = rsi_period
    context.oversold_level = oversold_level
    context.overbought_level = overbought_level
    context.position_pct = position_pct

def handle_data(context, data):
    stock = context.security
    
    rsi = data[stock].rsi(rsi_period, field='close')
    
    if rsi < context.oversold_level and context.portfolio.positions[stock].amount == 0:
        order_target_percent(stock, context.position_pct)
    elif rsi > context.overbought_level and context.portfolio.positions[stock].amount > 0:
        order_target_percent(stock, 0)

def output_schema():
    return {
        "signal": "bullish/bearish",
        "confidence": 0.0-1.0,
        "entry_zone": [entry_low, entry_high],
        "risk_line": stop_loss,
        "target_zone": [target_low, target_high],
        "evidence": ["RSI进入超卖/超买区域", "价格背离"]
    }
''',
        'parameters': [
            {'name': 'rsi_period', 'type': 'int', 'default': '14', 'description': 'RSI计算周期'},
            {'name': 'oversold_level', 'type': 'float', 'default': '30', 'description': '超卖阈值'},
            {'name': 'overbought_level', 'type': 'float', 'default': '70', 'description': '超买阈值'},
            {'name': 'position_pct', 'type': 'float', 'default': '0.2', 'description': '仓位比例'}
        ],
        'author': 'System',
        'is_system': True
    },
    {
        'name': 'KDJ随机指标策略',
        'description': '使用KDJ指标的交叉和超买超卖信号进行交易',
        'template_type': 'indicator',
        'code_template': '''my_strategy_name = "KDJ随机指标策略"
my_strategy_description = "使用KDJ指标的交叉和超买超卖信号进行交易"

# @param n int 9 RSV周期
# @param k_period int 3 K线周期
# @param d_period int 3 D线周期
# @param position_pct float 0.25 仓位比例

def initialize(context):
    context.n = n
    context.k_period = k_period
    context.d_period = d_period
    context.position_pct = position_pct

def handle_data(context, data):
    stock = context.security
    
    k, d, j = data[stock].kdj(n, k_period, d_period, field='close')
    
    if k < 20 and context.portfolio.positions[stock].amount == 0:
        order_target_percent(stock, context.position_pct)
    elif k > 80 and context.portfolio.positions[stock].amount > 0:
        order_target_percent(stock, 0)

def output_schema():
    return {
        "signal": "bullish/bearish",
        "confidence": 0.0-1.0,
        "entry_zone": [entry_low, entry_high],
        "risk_line": stop_loss,
        "target_zone": [target_low, target_high],
        "evidence": ["KDJ低位/高位金叉/死叉", "J值超买/超卖"]
    }
''',
        'parameters': [
            {'name': 'n', 'type': 'int', 'default': '9', 'description': 'RSV周期'},
            {'name': 'k_period', 'type': 'int', 'default': '3', 'description': 'K线周期'},
            {'name': 'd_period', 'type': 'int', 'default': '3', 'description': 'D线周期'},
            {'name': 'position_pct', 'type': 'float', 'default': '0.25', 'description': '仓位比例'}
        ],
        'author': 'System',
        'is_system': True
    },
    {
        'name': '布林带策略',
        'description': '基于布林带通道的价格突破和回归策略',
        'template_type': 'indicator',
        'code_template': '''my_strategy_name = "布林带策略"
my_strategy_description = "基于布林带通道的价格突破和回归策略"

# @param period int 20 布林带周期
# @param std_dev float 2.0 标准差倍数
# @param position_pct float 0.3 仓位比例

def initialize(context):
    context.period = period
    context.std_dev = std_dev
    context.position_pct = position_pct

def handle_data(context, data):
    stock = context.security
    
    upper, middle, lower = data[stock].boll(
        period, std_dev, field='close'
    )
    price = data[stock].close
    
    if price < lower and context.portfolio.positions[stock].amount == 0:
        order_target_percent(stock, context.position_pct)
    elif price > upper and context.portfolio.positions[stock].amount > 0:
        order_target_percent(stock, 0)

def output_schema():
    return {
        "signal": "bullish/bearish",
        "confidence": 0.0-1.0,
        "entry_zone": [entry_low, entry_high],
        "risk_line": stop_loss,
        "target_zone": [target_low, target_high],
        "evidence": ["价格触及布林带下轨/上轨", "波动率变化"]
    }
''',
        'parameters': [
            {'name': 'period', 'type': 'int', 'default': '20', 'description': '布林带周期'},
            {'name': 'std_dev', 'type': 'float', 'default': '2.0', 'description': '标准差倍数'},
            {'name': 'position_pct', 'type': 'float', 'default': '0.3', 'description': '仓位比例'}
        ],
        'author': 'System',
        'is_system': True
    },
    {
        'name': '成交量异常策略',
        'description': '基于成交量异常放大配合价格变化的选股策略',
        'template_type': 'selection',
        'code_template': '''my_strategy_name = "成交量异常策略"
my_strategy_description = "基于成交量异常放大配合价格变化的选股策略"

# @param vol_period int 20 成交量均线周期
# @param vol_multiplier float 2.0 成交量倍数
# @param price_change_min float 2.0 最小涨幅百分比
# @param position_pct float 0.3 仓位比例

def initialize(context):
    context.vol_period = vol_period
    context.vol_multiplier = vol_multiplier
    context.price_change_min = price_change_min
    context.position_pct = position_pct

def handle_data(context, data):
    stock = context.security
    
    vol_ma = data[stock].mavg(context.vol_period, field='volume')
    current_vol = data[stock].volume
    price_change = data[stock].pct_change(1)
    
    if current_vol > vol_ma * context.vol_multiplier and \
       price_change > context.price_change_min / 100 and \
       context.portfolio.positions[stock].amount == 0:
        order_target_percent(stock, context.position_pct)

def output_schema():
    return {
        "signal": "bullish/bearish",
        "confidence": 0.0-1.0,
        "entry_zone": [entry_low, entry_high],
        "risk_line": stop_loss,
        "target_zone": [target_low, target_high],
        "evidence": ["成交量异常放大", "价格同步上涨"]
    }
''',
        'parameters': [
            {'name': 'vol_period', 'type': 'int', 'default': '20', 'description': '成交量均线周期'},
            {'name': 'vol_multiplier', 'type': 'float', 'default': '2.0', 'description': '成交量倍数'},
            {'name': 'price_change_min', 'type': 'float', 'default': '2.0', 'description': '最小涨幅百分比'},
            {'name': 'position_pct', 'type': 'float', 'default': '0.3', 'description': '仓位比例'}
        ],
        'author': 'System',
        'is_system': True
    },
    {
        'name': '动量策略',
        'description': '基于价格动量效应的趋势跟踪策略',
        'template_type': 'momentum',
        'code_template': '''my_strategy_name = "动量策略"
my_strategy_description = "基于价格动量效应的趋势跟踪策略"

# @param lookback_period int 20 回溯期
# @param holding_period int 5 持有期
# @param position_pct float 0.4 仓位比例

def initialize(context):
    context.lookback_period = lookback_period
    context.holding_period = holding_period
    context.position_pct = position_pct
    context.holding_days = 0

def handle_data(context, data):
    stock = context.security
    
    momentum = data[stock].pct_change(context.lookback_period)
    
    if momentum > 0.05 and context.portfolio.positions[stock].amount == 0:
        order_target_percent(stock, context.position_pct)
        context.holding_days = 0
    
    if context.portfolio.positions[stock].amount > 0:
        context.holding_days += 1
        if context.holding_days >= context.holding_period:
            order_target_percent(stock, 0)

def output_schema():
    return {
        "signal": "bullish/bearish",
        "confidence": 0.0-1.0,
        "entry_zone": [entry_low, entry_high],
        "risk_line": stop_loss,
        "target_zone": [target_low, target_high],
        "evidence": ["动量指标为正", "价格持续上涨"]
    }
''',
        'parameters': [
            {'name': 'lookback_period', 'type': 'int', 'default': '20', 'description': '回溯期'},
            {'name': 'holding_period', 'type': 'int', 'default': '5', 'description': '持有期'},
            {'name': 'position_pct', 'type': 'float', 'default': '0.4', 'description': '仓位比例'}
        ],
        'author': 'System',
        'is_system': True
    },
    {
        'name': '均值回归策略',
        'description': '基于价格偏离均值的回归交易策略',
        'template_type': 'mean_reversion',
        'code_template': '''my_strategy_name = "均值回归策略"
my_strategy_description = "基于价格偏离均值的回归交易策略"

# @param ma_period int 20 均线周期
# @param std_threshold float 2.0 标准差阈值
# @param position_pct float 0.3 仓位比例

def initialize(context):
    context.ma_period = ma_period
    context.std_threshold = std_threshold
    context.position_pct = position_pct

def handle_data(context, data):
    stock = context.security
    
    ma = data[stock].mavg(context.ma_period, field='close')
    std = data[stock].mstd(context.ma_period, field='close')
    price = data[stock].close
    
    z_score = (price - ma) / std
    
    if z_score < -context.std_threshold and context.portfolio.positions[stock].amount == 0:
        order_target_percent(stock, context.position_pct)
    elif z_score > context.std_threshold and context.portfolio.positions[stock].amount > 0:
        order_target_percent(stock, 0)

def output_schema():
    return {
        "signal": "bullish/bearish",
        "confidence": 0.0-1.0,
        "entry_zone": [entry_low, entry_high],
        "risk_line": stop_loss,
        "target_zone": [target_low, target_high],
        "evidence": ["价格偏离均值超过阈值", "Z分数极端"]
    }
''',
        'parameters': [
            {'name': 'ma_period', 'type': 'int', 'default': '20', 'description': '均线周期'},
            {'name': 'std_threshold', 'type': 'float', 'default': '2.0', 'description': '标准差阈值'},
            {'name': 'position_pct', 'type': 'float', 'default': '0.3', 'description': '仓位比例'}
        ],
        'author': 'System',
        'is_system': True
    },
    {
        'name': '突破策略',
        'description': '基于价格突破关键阻力位/支撑位的交易策略',
        'template_type': 'breakout',
        'code_template': '''my_strategy_name = "突破策略"
my_strategy_description = "基于价格突破关键阻力位/支撑位的交易策略"

# @param lookback_period int 20 盘整周期
# @param breakout_threshold float 0.01 突破幅度阈值
# @param position_pct float 0.35 仓位比例

def initialize(context):
    context.lookback_period = lookback_period
    context.breakout_threshold = breakout_threshold
    context.position_pct = position_pct

def handle_data(context, data):
    stock = context.security
    
    high = data[stock].hhv(context.lookback_period, field='high')
    low = data[stock].llv(context.lookback_period, field='low')
    price = data[stock].close
    
    resistance = high
    support = low
    
    if price > resistance * (1 + context.breakout_threshold) and \
       context.portfolio.positions[stock].amount == 0:
        order_target_percent(stock, context.position_pct)
    elif price < support * (1 - context.breakout_threshold) and \
         context.portfolio.positions[stock].amount > 0:
        order_target_percent(stock, 0)

def output_schema():
    return {
        "signal": "bullish/bearish",
        "confidence": 0.0-1.0,
        "entry_zone": [entry_low, entry_high],
        "risk_line": stop_loss,
        "target_zone": [target_low, target_high],
        "evidence": ["价格突破前期高点/低点", "量能配合"]
    }
''',
        'parameters': [
            {'name': 'lookback_period', 'type': 'int', 'default': '20', 'description': '盘整周期'},
            {'name': 'breakout_threshold', 'type': 'float', 'default': '0.01', 'description': '突破幅度阈值'},
            {'name': 'position_pct', 'type': 'float', 'default': '0.35', 'description': '仓位比例'}
        ],
        'author': 'System',
        'is_system': True
    },
    {
        'name': '双均线金叉死叉策略',
        'description': '使用EMA快速线和慢速线的交叉信号进行交易',
        'template_type': 'indicator',
        'code_template': '''my_strategy_name = "双均线金叉死叉策略"
my_strategy_description = "使用EMA快速线和慢速线的交叉信号进行交易"

# @param fast_ma_period int 10 快速均线周期
# @param slow_ma_period int 30 慢速均线周期
# @param ma_type str "EMA" 均线类型
# @param position_pct float 0.3 仓位比例

def initialize(context):
    context.fast_ma_period = fast_ma_period
    context.slow_ma_period = slow_ma_period
    context.ma_type = ma_type
    context.position_pct = position_pct

def handle_data(context, data):
    stock = context.security
    
    if context.ma_type == "EMA":
        fast_ma = data[stock].ewm(span=context.fast_ma_period).mean()
        slow_ma = data[stock].ewm(span=context.slow_ma_period).mean()
    else:
        fast_ma = data[stock].mavg(context.fast_ma_period, field='close')
        slow_ma = data[stock].mavg(context.slow_ma_period, field='close')
    
    if fast_ma > slow_ma and context.portfolio.positions[stock].amount == 0:
        order_target_percent(stock, context.position_pct)
    elif fast_ma < slow_ma and context.portfolio.positions[stock].amount > 0:
        order_target_percent(stock, 0)

def output_schema():
    return {
        "signal": "bullish/bearish",
        "confidence": 0.0-1.0,
        "entry_zone": [entry_low, entry_high],
        "risk_line": stop_loss,
        "target_zone": [target_low, target_high],
        "evidence": ["均线形成金叉/死叉", "趋势确认"]
    }
''',
        'parameters': [
            {'name': 'fast_ma_period', 'type': 'int', 'default': '10', 'description': '快速均线周期'},
            {'name': 'slow_ma_period', 'type': 'int', 'default': '30', 'description': '慢速均线周期'},
            {'name': 'ma_type', 'type': 'str', 'default': '"EMA"', 'description': '均线类型'},
            {'name': 'position_pct', 'type': 'float', 'default': '0.3', 'description': '仓位比例'}
        ],
        'author': 'System',
        'is_system': True
    }
]


def init_system_templates():
    logger.info("开始初始化系统预设策略模板...")
    
    created_count = 0
    skipped_count = 0
    
    for template_data in SYSTEM_TEMPLATES:
        existing = StrategyTemplateV2.query.filter_by(
            name=template_data['name'],
            is_system=True
        ).first()
        
        if existing:
            logger.info(f"跳过已存在的模板: {template_data['name']}")
            skipped_count += 1
            continue
        
        try:
            template = StrategyTemplateService.create_template(
                name=template_data['name'],
                description=template_data['description'],
                template_type=template_data['template_type'],
                code_template=template_data['code_template'],
                author=template_data['author'],
                is_system=template_data['is_system']
            )
            
            if 'parameters' in template_data:
                template.parameters = template_data['parameters']
                db.session.commit()
            
            logger.info(f"成功创建模板: {template_data['name']}")
            created_count += 1
            
        except Exception as e:
            logger.error(f"创建模板失败 {template_data['name']}: {str(e)}")
            db.session.rollback()
    
    logger.info(f"初始化完成: 成功创建 {created_count} 个模板, 跳过 {skipped_count} 个已存在的模板")
    return created_count, skipped_count


if __name__ == '__main__':
    from app import create_app
    app = create_app()
    
    with app.app_context():
        created, skipped = init_system_templates()
        logger.info(f"总计: 创建 {created}, 跳过 {skipped}")
