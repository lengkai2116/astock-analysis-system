"""
阶段三功能测试脚本
"""
import requests
import json
from datetime import date

BASE_URL = "http://localhost:5000"

def test_health():
    """测试健康检查"""
    print("\n=== 测试健康检查 ===")
    try:
        response = requests.get(f"{BASE_URL}/api/v1/health")
        print(f"状态码: {response.status_code}")
        print(f"响应: {response.json()}")
        return response.status_code == 200
    except Exception as e:
        print(f"请求失败: {str(e)}")
        return False

def test_watchlist():
    """测试自选股接口"""
    print("\n=== 测试自选股接口 ===")
    
    # 获取自选股列表
    try:
        response = requests.get(f"{BASE_URL}/api/v3/watchlist")
        print(f"GET /api/v3/watchlist - 状态码: {response.status_code}")
        print(f"响应: {response.json()}")
    except Exception as e:
        print(f"请求失败: {str(e)}")
    
    # 添加自选股
    try:
        response = requests.post(
            f"{BASE_URL}/api/v3/watchlist",
            json={"ts_code": "000001.SZ", "notes": "测试自选股"}
        )
        print(f"POST /api/v3/watchlist - 状态码: {response.status_code}")
        print(f"响应: {response.json()}")
    except Exception as e:
        print(f"请求失败: {str(e)}")
    
    # 获取自选股列表
    try:
        response = requests.get(f"{BASE_URL}/api/v3/watchlist")
        print(f"GET /api/v3/watchlist - 状态码: {response.status_code}")
        data = response.json()
        if data.get('data'):
            return data['data'][0]['id']
    except Exception as e:
        print(f"请求失败: {str(e)}")
    return None

def test_portfolio():
    """测试投资组合接口"""
    print("\n=== 测试投资组合接口 ===")
    
    # 创建投资组合
    try:
        response = requests.post(
            f"{BASE_URL}/api/v3/portfolio",
            json={
                "name": "测试组合",
                "initial_capital": 1000000,
                "description": "这是一个测试投资组合"
            }
        )
        print(f"POST /api/v3/portfolio - 状态码: {response.status_code}")
        print(f"响应: {response.json()}")
        
        data = response.json()
        if data.get('success') and data.get('data'):
            portfolio_id = data['data']['id']
            
            # 模拟买入
            response = requests.post(
                f"{BASE_URL}/api/v3/portfolio/{portfolio_id}/trade",
                json={
                    "ts_code": "000001.SZ",
                    "trade_type": "buy",
                    "price": 10.5,
                    "quantity": 1000,
                    "reason": "测试买入"
                }
            )
            print(f"POST /api/v3/portfolio/{portfolio_id}/trade - 状态码: {response.status_code}")
            print(f"响应: {response.json()}")
            
            # 获取组合业绩
            response = requests.get(f"{BASE_URL}/api/v3/portfolio/{portfolio_id}/performance")
            print(f"GET /api/v3/portfolio/{portfolio_id}/performance - 状态码: {response.status_code}")
            print(f"响应: {response.json()}")
            
    except Exception as e:
        print(f"请求失败: {str(e)}")

def test_indicators():
    """测试技术指标接口"""
    print("\n=== 测试技术指标接口 ===")
    
    ts_code = "000001.SZ"
    
    # 计算技术指标
    try:
        response = requests.post(
            f"{BASE_URL}/api/v3/indicators/{ts_code}/calculate",
            json={"start_date": "2024-01-01", "end_date": date.today().strftime('%Y-%m-%d')}
        )
        print(f"POST /api/v3/indicators/{ts_code}/calculate - 状态码: {response.status_code}")
        print(f"响应: {response.json()}")
    except Exception as e:
        print(f"请求失败: {str(e)}")
    
    # 获取技术指标
    try:
        response = requests.get(f"{BASE_URL}/api/v3/indicators/{ts_code}")
        print(f"GET /api/v3/indicators/{ts_code} - 状态码: {response.status_code}")
        data = response.json()
        if data.get('data'):
            print(f"最近指标: {data['data'][0]}")
    except Exception as e:
        print(f"请求失败: {str(e)}")

def test_signals():
    """测试信号接口"""
    print("\n=== 测试信号接口 ===")
    
    ts_code = "000001.SZ"
    
    # 生成信号
    try:
        response = requests.post(
            f"{BASE_URL}/api/v3/signals/generate",
            json={"ts_code": ts_code}
        )
        print(f"POST /api/v3/signals/generate - 状态码: {response.status_code}")
        print(f"响应: {response.json()}")
    except Exception as e:
        print(f"请求失败: {str(e)}")
    
    # 获取信号
    try:
        response = requests.get(f"{BASE_URL}/api/v3/signals?ts_code={ts_code}&limit=10")
        print(f"GET /api/v3/signals - 状态码: {response.status_code}")
        data = response.json()
        if data.get('data'):
            print(f"最近信号: {len(data['data'])} 条")
            for signal in data['data'][:3]:
                print(f"  - {signal['signal_type']} @ {signal['entry_price']} ({signal['reason']})")
    except Exception as e:
        print(f"请求失败: {str(e)}")

def main():
    print("=" * 50)
    print("A股股票分析系统 - 阶段三功能测试")
    print("=" * 50)
    
    # 测试健康检查
    if not test_health():
        print("\n❌ 后端服务未启动，请先运行 docker-compose up -d")
        return
    
    # 测试自选股
    watchlist_id = test_watchlist()
    
    # 测试投资组合
    test_portfolio()
    
    # 测试技术指标
    test_indicators()
    
    # 测试信号
    test_signals()
    
    print("\n" + "=" * 50)
    print("测试完成！")
    print("=" * 50)

if __name__ == "__main__":
    main()
