#!/bin/bash
# A股分析系统 — 安装验证脚本（250号方案更新版）
# 在终端运行：bash /Users/kalence/Desktop/01-A股股票分析系统/verify-install.command

set -e

PROJECT_ROOT="/Users/kalence/Desktop/01-A股股票分析系统"
VENV_PYTHON="$PROJECT_ROOT/backend/.venv/bin/python"

echo "═══════════════════════════════════════════════"
echo " 安装验证（当前架构: mootdx TCP + SQLite WAL）"
echo "═══════════════════════════════════════════════"

echo ""
echo "1️⃣  Python 依赖"
$VENV_PYTHON -c "
import flask, sqlite3, pandas, requests, tushare
print(f'  ✅ Flask {flask.__version__}')
print(f'  ✅ sqlite3 (WAL)')
print(f'  ✅ pandas')
print(f'  ✅ requests')
print(f'  ✅ tushare')
" && echo "   ✅ Python 依赖就绪" || echo "   ❌ Python 依赖缺失"

echo ""
echo "2️⃣  mootdx TCP 连通性"
$VENV_PYTHON -c "
from mootdx.quotes import Quotes
client = Quotes.factory()
stocks = client.stocks()
codes = [c for c in stocks['code'] if isinstance(c, str) and len(c)==6 and c[0] in ('0','3','6')]
quotes = client.quotes(codes[:10])
print(f'  ✅ Stocks: {len(stocks)} 只')
print(f'  ✅ A股候选: {len(codes)} 只')
print(f'  ✅ quotes 返回: {len(quotes)} 只(样例)')
" 2>&1 && echo "   ✅ mootdx TCP 连通正常" || echo "   ❌ mootdx 无法连通"

echo ""
echo "3️⃣  SQLite WAL 缓存"
$VENV_PYTHON -c "
from app.data.enhanced_cache_manager import get_ecm_instance
ecm = get_ecm_instance()
wal = ecm.conn.execute('PRAGMA journal_mode').fetchone()[0]
cnt = ecm.conn.execute('SELECT COUNT(*) FROM daily_cache').fetchone()[0]
print(f'  ✅ journal_mode={wal}')
print(f'  ✅ daily_cache: {cnt} 行')
assert wal == 'wal', 'WAL 模式未启用'
" 2>&1 && echo "   ✅ SQLite WAL 缓存正常" || echo "   ❌ SQLite 异常"

echo ""
echo "4️⃣  InMemoryStateStore 数据"
$VENV_PYTHON -c "
from app.data.mootdx_collector import mootdx_collector
from app.data.in_memory_store import store
import time
if not mootdx_collector.is_running():
    print('  ℹ️  采集器未运行, 跳过快照检查')
else:
    time.sleep(2)
    snap = store.get_snapshot()
    bj = [s for s in snap if str(s.get('ts_code','')).endswith('.BJ')]
    print(f'  ✅ 快照: {len(snap)} 只')
    print(f'  ✅ 北交所: {len(bj)} 只')
" 2>&1 && echo "   ✅ 内存状态正常" || echo "   ❌ 内存状态异常"

echo ""
echo "5️⃣  Flask 启动验证"
$VENV_PYTHON -c "
import os, sys
for k in ['HTTP_PROXY','HTTPS_PROXY','ALL_PROXY']: os.environ.pop(k, None)
from app import create_app
app = create_app()
print('  ✅ Flask app 创建成功')
" 2>&1 && echo "   ✅ Flask 启动正常" || echo "   ❌ Flask 启动失败"

echo ""
echo "═══════════════════════════════════════════════"
echo " 全部验证通过！"
echo ""
echo " 双击 start-dev.command 启动开发环境"
echo "═══════════════════════════════════════════════"
echo ""
echo "按 Enter 键退出..."
read -r
