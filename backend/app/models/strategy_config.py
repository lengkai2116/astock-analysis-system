"""
策略模型配置预留
用于配置策略模型相关参数，待用户确认后添加

注意：此文件为配置预留，实际模型导入需在 models/__init__.py 中完成
"""

from app.models.strategy import StrategyOutput, StrategyTemplateV2, StrategySignal, StrategyTemplateType

# 策略模型配置
STRATEGY_MODEL_CONFIG = {
    # 模型导出配置（预留）
    'models': {
        'strategy_output': StrategyOutput,
        'strategy_template_v2': StrategyTemplateV2,
    },
    
    # 枚举值配置
    'enums': {
        'strategy_signal': StrategySignal,
        'template_type': StrategyTemplateType,
    },
    
    # 信号类型映射
    'signal_mapping': {
        'BULLISH': {'label': '看多', 'color': 'green', 'icon': 'rise'},
        'BEARISH': {'label': '看空', 'color': 'red', 'icon': 'fall'},
        'NEUTRAL': {'label': '中性', 'color': 'gray', 'icon': 'minus'},
        'WATCH': {'label': '观察', 'color': 'blue', 'icon': 'eye'},
    },
    
    # 模板类型映射
    'template_type_mapping': {
        'INDICATOR': {'label': '指标型', 'icon': 'line-chart'},
        'SELECTION': {'label': '选股型', 'icon': 'filter'},
        'PORTFOLIO': {'label': '组合型', 'icon': 'portfolio'},
    },
    
    # API路径配置
    'api_paths': {
        'strategy_outputs': '/api/v2/strategy/outputs',
        'strategy_templates': '/api/v2/strategy/templates',
    },
}

def get_strategy_model_config():
    """获取策略模型配置"""
    return STRATEGY_MODEL_CONFIG

def is_model_registered():
    """检查模型是否已注册到db"""
    from app import db
    try:
        # 检查表是否存在
        db.engine.execute("SELECT 1 FROM strategy_outputs LIMIT 1")
        return True
    except Exception:
        return False

def register_models():
    """
    注册策略模型到db
    注意：实际通过 db.create_all() 自动注册
    此函数用于预留配置检查
    """
    from app import db
    
    models_to_check = [
        ('StrategyOutput', StrategyOutput),
        ('StrategyTemplateV2', StrategyTemplateV2),
    ]
    
    registered = []
    for name, model in models_to_check:
        try:
            db.engine.execute(f"SELECT 1 FROM {model.__tablename__} LIMIT 1")
            registered.append(name)
        except Exception:
            pass
    
    return registered
