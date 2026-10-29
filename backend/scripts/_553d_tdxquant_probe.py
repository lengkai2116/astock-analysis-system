"""553-D：TdxQuant 接入可行性探针（只读，不写库、不启采集器）。

检查两条路径：
1. tqcenter：本地通达信 TQ 客户端 HTTP 127.0.0.1:17709 是否可达；
2. tqserver/TdxAiData：`tdxaidata` 包 + `TdxAiData.ini` 数据服务 Key 是否就位。

任一可用则打印下一步验证命令；都不可用则输出 BLOCKED 与所需前提，退出码 2。
用法：
    cd backend && .venv/bin/python3 -u scripts/_553d_tdxquant_probe.py
"""
import importlib.util
import json
import os
import sys
import urllib.request

TIMEOUT = 3
INI_CANDIDATES = [
    os.path.join(os.getcwd(), 'TdxAiData.ini'),
    os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'TdxAiData.ini'),
    os.path.expanduser('~/TdxAiData.ini'),
]


def probe_client(timeout: int = TIMEOUT) -> dict:
    """探测本地 TQ 客户端 HTTP 端口（get_market_data 最小请求）。"""
    body = json.dumps({
        'id': 1,
        'method': 'get_market_data',
        'params': {'stock_list': ['000001.SZ'], 'period': '1d', 'count': 5},
    }).encode('utf-8')
    req = urllib.request.Request(
        'http://127.0.0.1:17709/', data=body,
        headers={'Content-Type': 'application/json'}, method='POST')
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read().decode('utf-8', 'ignore')
        return {'ok': True, 'http': resp.status, 'sample': raw[:300]}
    except Exception as e:
        return {'ok': False, 'error': f'{type(e).__name__}: {e}'}


def probe_tqserver() -> dict:
    """探测 tdxaidata 包与 TdxAiData.ini。"""
    has_pkg = importlib.util.find_spec('tdxaidata') is not None
    ini = next((p for p in INI_CANDIDATES if os.path.isfile(p)), None)
    return {'package': has_pkg, 'ini': ini}


def decide(client: dict, server: dict) -> str:
    """纯决策函数（便于测试）：client / tqserver / blocked。"""
    if client.get('ok'):
        return 'client'
    if server.get('package') and server.get('ini'):
        return 'tqserver'
    return 'blocked'


def main() -> int:
    client = probe_client()
    server = probe_tqserver()
    mode = decide(client, server)
    out = {'mode': mode, 'client': client, 'tqserver': server}
    print(json.dumps(out, ensure_ascii=False, indent=2))
    if mode == 'client':
        print('\n下一步：用 HTTP get_market_data 取 000001.SZ 日线，与 Tushare/mootdx 对字段与当日可采时点。')
        return 0
    if mode == 'tqserver':
        print('\n下一步：tqs.get_market_data 取 000001.SZ 日线做字段/时点对比（Key 已就位）。')
        return 0
    print('\nBLOCKED：缺少 TdxQuant 运行前提。')
    print('  路径 A（tqcenter）：安装并启动支持 TQ 的通达信终端，确认 127.0.0.1:17709 可访问。')
    print('  路径 B（tqserver）：pip install tdxaidata，并在 TdxAiData.ini 配置数据服务 Key。')
    print('  注意：同花顺 line 已实测当日 20:28 仍未更新，不纳入；本探针只验证 TdxQuant。')
    return 2


if __name__ == '__main__':
    sys.exit(main())
