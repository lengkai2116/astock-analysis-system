"""
API 健康检查集成测试
"""
import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from app import create_app


def test_health_endpoint():
    """测试健康检查接口"""
    app = create_app()
    with app.test_client() as client:
        resp = client.get('/api/v3/health')
        assert resp.status_code == 200
        data = resp.get_json()
        assert data['success'] is True
        assert data['status'] == 'healthy'


def test_health_v1_endpoint():
    """测试 v1 健康检查接口"""
    app = create_app()
    with app.test_client() as client:
        resp = client.get('/api/v1/health')
        assert resp.status_code == 200
        data = resp.get_json()
        assert data['success'] is True


def test_health_options():
    """测试 OPTIONS 请求"""
    app = create_app()
    with app.test_client() as client:
        resp = client.options('/api/v3/health')
        assert resp.status_code == 200
        assert 'Access-Control-Allow-Origin' in resp.headers


def test_cors_headers():
    """测试 CORS 头"""
    app = create_app()
    with app.test_client() as client:
        resp = client.get('/api/v3/health')
        assert resp.headers.get('Access-Control-Allow-Origin') is not None
        assert resp.headers.get('Access-Control-Allow-Methods') is not None


if __name__ == '__main__':
    test_health_endpoint()
    test_health_v1_endpoint()
    test_health_options()
    test_cors_headers()
    print("✅ 所有 API 健康检查测试通过")
