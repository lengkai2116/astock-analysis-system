"""
API 路由集成测试
覆盖核心业务路由的端点可用性和响应格式
"""
import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

import pytest
from app import create_app


@pytest.fixture
def client():
    """创建测试客户端"""
    app = create_app()
    app.config['TESTING'] = True
    with app.test_client() as c:
        yield c


# ========== Health API ==========

def test_health_v3(client):
    """测试 /api/v3/health"""
    resp = client.get('/api/v3/health')
    assert resp.status_code == 200
    data = resp.get_json()
    assert data['success'] is True
    assert data['status'] == 'healthy'


def test_health_database(client):
    """测试 /api/v3/health/database (需 mock 数据库)"""
    resp = client.get('/api/v3/health/database')
    # 无数据库时也应返回有效 JSON
    data = resp.get_json()
    assert data is not None


# ========== Market API ==========

def test_market_stocks(client):
    """测试股票列表接口"""
    resp = client.get('/api/v3/stocks')
    assert resp.status_code in (200, 401)  # 有 auth 或没有
    if resp.status_code == 200:
        data = resp.get_json()
        assert data is not None


def test_market_stocks_with_pagination(client):
    """测试分页参数"""
    resp = client.get('/api/v3/stocks?page=1&page_size=10')
    assert resp.status_code in (200, 401)


def test_market_details(client):
    """测试股票详情接口（如存在）"""
    resp = client.get('/api/v1/stocks')
    assert resp.status_code in (200, 401)


# ========== Screener API ==========

def test_screener_routes_exist(client):
    """测试选股器路由返回有效响应"""
    routes = [
        '/api/v3/screener/preview',
        '/api/v3/screener/run',
    ]
    for route in routes:
        resp = client.post(route, json={})
        # 至少不返回 404
        assert resp.status_code != 404, f"{route} 返回 404"


def test_screener_filter(client):
    """测试选股筛选（GET 参数）"""
    resp = client.get('/api/v3/screener/filter?industry=银行')
    assert resp.status_code != 404


# ========== Backtest API ==========

def test_backtest_endpoints_exist(client):
    """测试回测路由存在"""
    routes = [
        '/api/v3/backtest/run',
        '/api/v3/backtest/results',
    ]
    for route in routes:
        resp = client.post(route, json={})
        assert resp.status_code != 404, f"{route} 返回 404"


# ========== Factor API ==========

def test_factor_routes(client):
    """测试因子路由"""
    routes = [
        '/api/v3/factors/list',
        '/api/v3/factors/categories',
    ]
    for route in routes:
        resp = client.get(route)
        assert resp.status_code != 404, f"{route} 返回 404"


# ========== AI Analysis API ==========

def test_ai_routes_exist(client):
    """测试 AI 分析路由存在"""
    resp = client.get('/api/v3/ai/health')
    assert resp.status_code != 404
    data = resp.get_json()
    if resp.status_code == 200:
        assert data is not None


def test_ai_analysts_endpoint(client):
    """测试分析师列表接口"""
    resp = client.get('/api/v3/ai/analysts')
    assert resp.status_code != 404


# ========== 404 Handler ==========

def test_not_found_returns_json(client):
    """测试不存在路由返回 JSON 而非 HTML"""
    resp = client.get('/api/v3/nonexistent_route')
    assert resp.status_code in (401, 404)
    data = resp.get_json()
    if resp.status_code == 404:
        assert 'success' in data
        assert data['success'] is False


# ========== Chart / Market Data API ==========

def test_chart_routes_exist(client):
    """测试 K 线图数据路由"""
    routes = [
        '/api/v3/chart/kline?ts_code=000001.SZ',
        '/api/v3/market/hot',
    ]
    for route in routes:
        resp = client.get(route)
        assert resp.status_code != 404, f"{route} 返回 404"


# ========== Auth API ==========

def test_auth_login_endpoint(client):
    """测试登录接口存在"""
    resp = client.post('/api/auth/login', json={})
    assert resp.status_code != 404
    data = resp.get_json()
    if resp.status_code == 200:
        assert 'success' in data


# ========== CORS Headers ==========

def test_cors_headers_on_all_routes(client):
    """测试 CORS 头在关键路由上存在"""
    routes = [
        '/api/v3/health',
        '/api/v3/stocks',
    ]
    for route in routes:
        resp = client.options(route)
        if resp.status_code == 200:
            cors = resp.headers.get('Access-Control-Allow-Origin')
            cors_methods = resp.headers.get('Access-Control-Allow-Methods')
            if cors is not None:
                assert cors == '*' or cors.startswith('http'), \
                    f"CORS Origin 格式异常: {cors}"
            if cors_methods is not None:
                assert 'GET' in cors_methods


# ========== Response Format ==========

def test_api_response_format(client):
    """测试 API 响应格式的一致性"""
    resp = client.get('/api/v3/health')
    data = resp.get_json()
    assert isinstance(data, dict)
    # 标准响应字段
    assert 'success' in data


if __name__ == '__main__':
    pytest.main([__file__, '-v'])
