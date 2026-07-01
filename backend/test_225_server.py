"""225号系统管理模块专用测试服务器 — 不依赖 app/__init__.py"""
import os, sys
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..'))
os.environ['DATA_DIR'] = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'data')

# === 在导入任何 app.* 模块前，先建立虚拟 app 包 ===
import types
app_pkg = types.ModuleType('app')
app_pkg.__path__ = [os.path.join(os.path.dirname(os.path.abspath(__file__)), 'app')]
sys.modules['app'] = app_pkg

from flask import Flask, jsonify, request, Blueprint
from flask_sqlalchemy import SQLAlchemy

app = Flask(__name__)
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///:memory:'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
app.config['SECRET_KEY'] = 'test'

db = SQLAlchemy(app)

# 将 db 注册到 app 包
app_pkg.db = db

# === 现在可以安全导入 app 子模块 ===
from app.models.system_config import SystemConfig, SyncLog
from app.services.runtime_config import RuntimeConfigManager

rcm = RuntimeConfigManager()

# ── 健康检查 ──
health_bp = Blueprint('health', __name__)

@health_bp.route('/api/v3/health', methods=['GET'])
def health_check():
    return jsonify({
        'success': True,
        'data': {
            'status': 'healthy',
            'services': [
                {'name': 'SQLite (test)', 'status': 'healthy', 'latency': 1},
                {'name': 'TTLCache (内存缓存)', 'status': 'healthy', 'maxsize': 1000},
                {'name': 'DuckDB (缓存)', 'status': 'simulated', 'records': 6372},
                {'name': 'Backend (Flask)', 'status': 'healthy'},
                {'name': '静态托管', 'status': 'healthy'},
                {'name': 'WebSocket', 'status': 'connected'},
            ],
            'system': {'uptime': '0天', 'python_version': '3.9', 'framework_version': 'v2.0.0',
                       'frontend_version': 'Vue 3.5 + AntDV 4.2', 'data_last_update': '2026-07-01 07:00',
                       'data_dir': os.environ.get('DATA_DIR', 'default')},
            'data_sources': [
                {'name': 'Tushare Pro', 'status': 'connected'},
                {'name': 'AKShare', 'status': 'ready'},
                {'name': 'QMT', 'status': 'disconnected'},
            ],
            'cache': {'duckdb_file': '128 MB', 'daily_cached': 6372, 'minute_cached': 0,
                      'factor_precompute': 'pending', 'last_refresh': '2026-07-01 07:00'},
        }
    })

@health_bp.route('/api/v3/health/live', methods=['GET'])
def liveness():
    return jsonify({'success': True, 'status': 'alive'})

@health_bp.route('/api/v3/health/ready', methods=['GET'])
def readiness():
    return jsonify({'success': True, 'status': 'ready', 'dependencies': {'database': {'status': 'healthy'}, 'cache': {'status': 'healthy'}}})

@health_bp.route('/api/v3/health/database', methods=['GET'])
def database_check():
    from sqlalchemy import text
    try:
        db.session.execute(text('SELECT 1'))
        return jsonify({'success': True, 'status': 'healthy'})
    except Exception as e:
        return jsonify({'success': False, 'status': 'unhealthy', 'message': str(e)})

# ── 系统管理 ──
system_bp = Blueprint('system', __name__, url_prefix='/api/v3/system')

DEFAULT_SCHEDULING = {
    "daily_sync": {"enabled": True, "trigger_time": "15:30", "mode": "incremental",
                   "data_types": ["daily", "basic", "moneyflow", "index", "adj_factor"],
                   "warmup_cache": True, "timeout_minutes": 30},
    "intraday": {"enabled": True, "moneyflow_interval_min": 30, "index_mode": "on_demand", "quote_ttl_sec": 3},
    "analysis": {"weekly_eval": {"enabled": True, "day_of_week": "mon", "time": "06:00"},
                  "health_check": {"enabled": True, "day_of_week": "mon", "time": "06:30"},
                  "weekly_report": {"enabled": True, "day_of_week": "sun", "time": "20:00"},
                  "param_plateau": {"enabled": True, "day_of_month": 1, "time": "05:00"}},
    "monitor": {"default_scan_interval_min": 15, "post_market_eval_time": "15:30", "auto_sleep": {"enabled": True}},
}

@system_bp.route('/config/load', methods=['GET'])
def load_config():
    return jsonify({'success': True, 'data': {
        'llm': rcm.get('llm', {}),
        'data_source': rcm.get('data_source', {}),
        'notification': rcm.get('notification', {}),
    }})

@system_bp.route('/config/save', methods=['POST'])
def save_config():
    data = request.get_json()
    if not data:
        return jsonify({'success': False, 'error': '请求体不能为空'}), 400
    rcm.save(data)
    return jsonify({'success': True, 'message': '配置已保存（运行时热更新）'})

@system_bp.route('/data-source/status', methods=['GET'])
def ds_status():
    return jsonify({'success': True, 'data': {'sources': [
        {'name': 'Tushare Pro', 'status': 'connected', 'priority': 0},
        {'name': 'AKShare', 'status': 'ready', 'priority': -1},
        {'name': 'QMT', 'status': 'disconnected', 'priority': -2},
    ]}})

@system_bp.route('/schedule/config', methods=['GET'])
def get_schedule():
    config = rcm.get('scheduling', DEFAULT_SCHEDULING)
    return jsonify({'success': True, 'data': config})

@system_bp.route('/schedule/config', methods=['POST'])
def save_schedule():
    data = request.get_json()
    if not data:
        return jsonify({'success': False, 'error': '请求体不能为空'}), 400
    current = rcm.get('scheduling', DEFAULT_SCHEDULING)
    merged = {**current, **data}
    rcm.save_section('scheduling', merged)
    return jsonify({'success': True, 'message': '调度配置已保存，定时任务已动态更新'})

@system_bp.route('/schedule/logs', methods=['GET'])
def get_logs():
    logs = SyncLog.query.order_by(SyncLog.started_at.desc()).limit(20).all()
    return jsonify({'success': True, 'data': {'logs': [l.to_dict() for l in logs], 'total': len(logs)}})

@system_bp.route('/schedule/next-runs', methods=['GET'])
def next_runs():
    return jsonify({'success': True, 'data': {'jobs': [
        {'id': 'daily_close_sync', 'name': '日终数据同步', 'next_run': '2026-07-01T15:30:00'},
        {'id': 'weekly_eval', 'name': '周度赢率评估', 'next_run': '2026-07-06T06:00:00'},
    ]}})

@system_bp.route('/schedule/sync-now', methods=['POST'])
def sync_now():
    return jsonify({'success': True, 'data': {'status': 'started', 'records_added': 0, 'data_types': []}, 'message': '同步已启动（测试模拟）'})

@system_bp.route('/logs', methods=['GET'])
def sys_logs():
    return jsonify({'success': True, 'data': {'logs': [
        {'time': '07:00:00', 'level': 'info', 'message': '✅ 系统启动完成'},
        {'time': '07:00:01', 'level': 'info', 'message': '✅ RuntimeConfigManager 配置已加载'},
        {'time': '07:00:02', 'level': 'info', 'message': '✅ APScheduler 已初始化'},
    ], 'total': 3, 'level': 'all'}})

app.register_blueprint(health_bp)
app.register_blueprint(system_bp)

@app.after_request
def add_cors(response):
    response.headers['Access-Control-Allow-Origin'] = '*'
    return response

if __name__ == '__main__':
    with app.app_context():
        db.create_all()
        rcm.load()
        if not rcm.get_all():
            rcm.save({
                'llm': {'provider': 'mock', 'deepseek_api_key': ''},
                'data_source': {'tushare_token': 'test_token'},
                'notification': {'smtp': {'host':'', 'port':587, 'username':'', 'password':'', 'to':''}, 'webhook_url': ''},
                'scheduling': DEFAULT_SCHEDULING,
            })
        print("🚀 225测试服务器启动 → http://localhost:15001")
    app.run(host='0.0.0.0', port=15001, debug=False)
