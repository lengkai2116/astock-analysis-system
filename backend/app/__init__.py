import os
from flask import Flask
from flask_sqlalchemy import SQLAlchemy
from flask_migrate import Migrate
from flask_socketio import SocketIO
from dotenv import load_dotenv

load_dotenv()

db = SQLAlchemy()
migrate = Migrate()
socketio = SocketIO(cors_allowed_origins="*")

def create_app():
    app = Flask(__name__)
    
    @app.after_request
    def add_cors_headers(response):
        response.headers['Access-Control-Allow-Origin'] = '*'
        response.headers['Access-Control-Allow-Methods'] = 'GET, POST, PUT, DELETE, OPTIONS'
        response.headers['Access-Control-Allow-Headers'] = 'Content-Type, Authorization'
        return response
    
    app.config['SQLALCHEMY_DATABASE_URI'] = os.getenv('DATABASE_URL')
    app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
    app.config['SECRET_KEY'] = os.getenv('SECRET_KEY', 'dev')
    
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
    app.register_blueprint(qmt_bp)
    
    return app

from app import models

import logging
logger = logging.getLogger(__name__)
