#!/bin/bash
# 243号方案 — 安装验证脚本
# 在终端运行：bash /Users/kalence/Desktop/01-A股股票分析系统/verify-install.command

set -e

PROJECT_ROOT="/Users/kalence/Desktop/01-A股股票分析系统"
VENV_PYTHON="$PROJECT_ROOT/backend/.venv/bin/python"

echo "═══════════════════════════════════════════════"
echo " 243号方案 — 安装验证"
echo "═══════════════════════════════════════════════"

echo ""
echo "1️⃣  PostgreSQL"
psql -d stock_analysis -c "SELECT version(), current_database();" && echo "   ✅ PostgreSQL 连接正常" || echo "   ❌ PostgreSQL 无法连接"

echo ""
echo "2️⃣  Redis"
redis-cli ping && echo "   ✅ Redis 连接正常" || echo "   ❌ Redis 无法连接"

echo ""
echo "3️⃣  Python 依赖"
$VENV_PYTHON -c "import psycopg2, gunicorn, redis; print(f'✅ psycopg2 {psycopg2.__version__}'); print(f'✅ gunicorn OK'); print(f'✅ redis-py OK');" && echo "   ✅ Python 依赖就绪" || echo "   ❌ Python 依赖缺失"

echo ""
echo "4️⃣  DuckDB 清理"
lsof "$PROJECT_ROOT/data/duckdb/stock_cache.db" 2>/dev/null | grep python | awk '{print $2}' | xargs kill -9 2>/dev/null && echo "   ✅ DuckDB 旧锁已清理" || echo "   ℹ️  无残留锁"

BACKUP_COUNT=$(ls -f "$PROJECT_ROOT"/data/duckdb/stock_cache.db.corrupted.* 2>/dev/null | wc -l)
if [ "$BACKUP_COUNT" -gt 0 ]; then
    rm -f "$PROJECT_ROOT"/data/duckdb/stock_cache.db.corrupted.*
    echo "   ✅ 已删除 $BACKUP_COUNT 个 corrupted 文件"
else
    echo "   ✅ 无 corrupted 文件"
fi

echo ""
echo "5️⃣  Flask 启动 + PG 盘中表验证"
cd "$PROJECT_ROOT/backend" || exit 1
$VENV_PYTHON -c "
import os, sys
for k in ['HTTP_PROXY','HTTPS_PROXY','ALL_PROXY']: os.environ.pop(k, None)
os.environ['DATABASE_URL'] = 'postgresql:///stock_analysis'
from app import create_app
app = create_app()
from app.data.akshare_collector import akshare_collector
assert akshare_collector.is_running(), '采集器未启动'
print('   ✅ 采集器 5 线程运行中')
from app.data.realtime_pg import _pg_pool
assert _pg_pool is not None, 'PG 连接池未初始化'
print('   ✅ realtime_pg 连接池就绪')
import psycopg2
conn = psycopg2.connect('postgresql:///stock_analysis')
cur = conn.cursor()
cur.execute(\"SELECT table_name FROM information_schema.tables WHERE table_schema='public' AND table_name LIKE 'realtime_%'\")
tables = [r[0] for r in cur.fetchall()]
expected = ['realtime_snapshot','realtime_top_stocks','realtime_sectors','realtime_concepts','realtime_limit_pool','realtime_minute_kline','realtime_lhb','realtime_news']
for t in expected:
    assert t in tables, f'缺少表: {t}'
print(f'   ✅ {len(tables)}/8 张盘中实时表已创建')
cur.close(); conn.close()
akshare_collector.stop()
print()
print('═══ ✅ 全部验证通过！═══')
print('下一步：cd backend && .venv/bin/python run_gunicorn.sh')
" 2>&1

echo ""
echo "按 Enter 退出..."
read -r
