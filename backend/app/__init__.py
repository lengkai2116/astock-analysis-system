import os
from flask import Flask, request
from flask_sqlalchemy import SQLAlchemy
from flask_migrate import Migrate
from flask_socketio import SocketIO
from dotenv import load_dotenv

load_dotenv()

db = SQLAlchemy()
migrate = Migrate()
socketio = SocketIO(cors_allowed_origins="*")


import logging
from logging.handlers import TimedRotatingFileHandler

logger = logging.getLogger(__name__)

def _setup_logging(app):
    """配置日志轮转"""
    log_dir = os.environ.get('LOG_DIR', os.path.join(os.path.dirname(app.instance_path), 'logs'))
    os.makedirs(log_dir, exist_ok=True)
    
    log_file = os.path.join(log_dir, 'app.log')
    handler = TimedRotatingFileHandler(log_file, when='midnight', backupCount=30)
    handler.setFormatter(logging.Formatter(
        '%(asctime)s [%(levelname)s] %(name)s: %(message)s',
        datefmt='%Y-%m-%d %H:%M:%S'
    ))
    handler.setLevel(logging.INFO)
    
    # 替换 root logger 的 handler
    root_logger = logging.getLogger()
    root_logger.setLevel(logging.INFO)
    root_logger.addHandler(handler)
    
    # 同时保留控制台输出
    console = logging.StreamHandler()
    console.setFormatter(logging.Formatter(
        '%(asctime)s [%(levelname)s] %(name)s: %(message)s'
    ))
    console.setLevel(logging.INFO)
    root_logger.addHandler(console)
    
    app.logger.info(f"日志已配置: {log_file}")



def create_app():
    app = Flask(__name__)
    
    @app.after_request
    def add_cors_headers(response):
        allowed = os.environ.get('CORS_ORIGIN', '*')
        response.headers['Access-Control-Allow-Origin'] = allowed
        response.headers['Access-Control-Allow-Methods'] = 'GET, POST, PUT, DELETE, OPTIONS'
        response.headers['Access-Control-Allow-Headers'] = 'Content-Type, Authorization'
        return response
    
    # 全局请求鉴权（如已配置 AUTH_TOKEN）
    from app.auth import is_auth_enabled, _constant_time_compare
    
    _AUTH_TOKEN = os.environ.get('AUTH_TOKEN', '').strip()
    
    @app.before_request
    def check_auth():
        from flask import request
        if request.method == 'OPTIONS':
            return
        if not _AUTH_TOKEN:
            return
        path = request.path
        whitelist = ['/api/v1/health', '/api/v3/health', '/api/auth/login', '/api/auth/status']
        if any(path.startswith(w) for w in whitelist):
            return
        auth = request.headers.get('Authorization', '')
        if not auth.startswith('Bearer '):
            return {'success': False, 'error': '缺少认证令牌', 'error_type': 'AuthRequired'}, 401
        token = auth[7:]
        if not _constant_time_compare(token, _AUTH_TOKEN):

            return {'success': False, 'error': '认证令牌无效', 'error_type': 'AuthInvalid'}, 403
    

    @app.errorhandler(404)
    def not_found(error):
        """404 统一 JSON 响应"""
        return {"success": False, "error": "请求的资源不存在", "error_type": "NotFound"}, 404

    @app.errorhandler(500)
    def internal_error(error):
        """500 统一 JSON 响应"""
        return {"success": False, "error": "服务器内部错误", "error_type": "InternalError"}, 500

    @app.errorhandler(400)
    def bad_request(error):
        """400 统一 JSON 响应"""
        return {"success": False, "error": "请求参数错误", "error_type": "BadRequest"}, 400

    @app.errorhandler(401)
    def unauthorized(error):
        """401 统一 JSON 响应"""
        return {"success": False, "error": "未授权，请提供有效的认证令牌", "error_type": "Unauthorized"}, 401

    @app.errorhandler(403)
    def forbidden(error):
        """403 统一 JSON 响应"""
        return {"success": False, "error": "权限不足", "error_type": "Forbidden"}, 403

    @app.errorhandler(405)
    def method_not_allowed(error):
        """405 统一 JSON 响应"""
        return {"success": False, "error": "请求方法不允许", "error_type": "MethodNotAllowed"}, 405

    @app.errorhandler(429)
    def rate_limit_exceeded(error):
        """429 统一 JSON 响应"""
        return {"success": False, "error": "请求过于频繁，请稍后再试", "error_type": "RateLimited"}, 429

    @app.errorhandler(502)
    def bad_gateway(error):
        """502 统一 JSON 响应"""
        return {"success": False, "error": "上游服务异常", "error_type": "BadGateway"}, 502

    @app.errorhandler(503)
    def service_unavailable(error):
        """503 统一 JSON 响应"""
        return {"success": False, "error": "服务暂时不可用", "error_type": "ServiceUnavailable"}, 503

    app.config['SQLALCHEMY_DATABASE_URI'] = os.getenv('DATABASE_URL')
    app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
    app.config['SECRET_KEY'] = os.getenv('SECRET_KEY', 'dev')
    
    _setup_logging(app)
    db.init_app(app)
    migrate.init_app(app, db)
    socketio.init_app(app, cors_allowed_origins="*")
    
    from app.routes.market import market_bp
    from app.routes.health import health_bp
    from app.routes.phase3 import phase3_bp
    from app.routes.cache import cache_bp
    from app.routes.chart import chart_bp
    from app.routes.realtime import realtime_bp
    from app.routes.ai_analysis import ai_analysis_bp
    from app.routes.factors import factors_bp
    from app.routes.strategy import strategy_bp
    from app.routes.backtest import backtest_bp
    from app.routes.indicator_ide import indicator_ide_bp
    from app.routes.reports import reports_bp
    from app.routes.screener import screener_bp
    from app.routes.strategy_templates import strategy_templates_bp
    from app.routes.qmt import qmt_bp
    from app.routes.virtual_verify import verify_bp
    from app.routes.account import account_bp
    from app.auth import auth_bp
    from app.routes.minute_data import minute_data_bp
    from app.routes.playback import playback_bp
    from app.routes.resonance import resonance_bp
    from app.routes.prediction import prediction_bp
    from app.routes.strategy_interpret import strategy_interpret_bp
    from app.routes.kline_resampler_api import kline_resampler_bp
    from app.routes.news_route import news_bp
    from app.routes.alert_route import alert_bp
    
    app.register_blueprint(market_bp)
    app.register_blueprint(health_bp)
    app.register_blueprint(phase3_bp)
    app.register_blueprint(cache_bp)
    app.register_blueprint(chart_bp)
    app.register_blueprint(realtime_bp)
    app.register_blueprint(ai_analysis_bp)
    app.register_blueprint(factors_bp)
    app.register_blueprint(strategy_bp)
    app.register_blueprint(backtest_bp)
    app.register_blueprint(indicator_ide_bp)
    app.register_blueprint(reports_bp)
    app.register_blueprint(screener_bp)
    app.register_blueprint(strategy_templates_bp)
    app.register_blueprint(verify_bp)
    app.register_blueprint(qmt_bp)
    app.register_blueprint(account_bp)
    app.register_blueprint(auth_bp)
    app.register_blueprint(minute_data_bp)
    app.register_blueprint(playback_bp)
    app.register_blueprint(resonance_bp)
    app.register_blueprint(prediction_bp)
    app.register_blueprint(strategy_interpret_bp)
    app.register_blueprint(kline_resampler_bp)
    app.register_blueprint(news_bp)
    app.register_blueprint(alert_bp)

    

    # ============================================================
    # 观潮对标服务初始化
    # ============================================================

    # 1. 数据源管理器注册
    try:
        from app.data.data_source_manager import data_source_manager
        from app.data.tushare_provider import TushareProvider
        from app.data.akshare_provider import AkshareProvider

        # 注册 Tushare 作为主数据源
        tushare = TushareProvider()
        data_source_manager.register_source('tushare', lambda ep, p: _route_provider(ep, p, tushare), priority=0)

        # 注册 AKShare 作为备用数据源
        try:
            akshare = AkshareProvider()
            data_source_manager.register_source('akshare', lambda ep, p: _route_provider(ep, p, akshare), priority=1)
        except Exception:
            logger.warning("AKShare provider 注册失败（可忽略）")

        logger.info("数据源管理器初始化完成")
    except Exception as e:
        logger.warning(f"数据源管理器初始化失败（可忽略）: {e}")



    return app

def _route_provider(endpoint, params, provider):
    """路由数据提供者请求"""
    if endpoint == 'health_check':
        return {'status': 'ok'}
    if endpoint == 'get_kline':
        return provider.get_daily_data(params.get('ts_code'), params.get('start_date'), params.get('end_date'))
    if endpoint == 'get_stock_list':
        return provider.get_stock_list()
    return provider.get_daily_data(endpoint, params)



