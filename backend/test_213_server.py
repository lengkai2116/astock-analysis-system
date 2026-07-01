"""213号仪表盘专用测试服务器 — 不依赖 app/__init__.py 的完整导入链"""
import os, sys
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..'))
os.environ['DATA_DIR'] = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'data')

import types
app_pkg = types.ModuleType('app')
app_pkg.__path__ = [os.path.join(os.path.dirname(os.path.abspath(__file__)), 'app')]
sys.modules['app'] = app_pkg

from flask import Flask, jsonify
from flask_sqlalchemy import SQLAlchemy

test_app = Flask(__name__)
test_app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///:memory:'
test_app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
test_app.config['SECRET_KEY'] = 'test'

db = SQLAlchemy(test_app)
app_pkg.db = db

# 注册所有需要的 Blueprint
from app.routes.market import market_bp
from app.routes.chart import chart_bp
from app.routes.dashboard import dashboard_bp
from app.routes.health import health_bp

test_app.register_blueprint(market_bp)
test_app.register_blueprint(chart_bp)
test_app.register_blueprint(dashboard_bp)
test_app.register_blueprint(health_bp)

@test_app.after_request
def add_cors(response):
    response.headers['Access-Control-Allow-Origin'] = '*'
    return response

if __name__ == '__main__':
    print("🚀 213仪表盘测试服务器启动 → http://localhost:15002")
    test_app.run(host='0.0.0.0', port=15002, debug=False)
