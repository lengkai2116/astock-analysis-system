"""498号 批次6 验证探针（只读）：#8 tushare 死段删除 / Q3 MinuteDataManager 删除 / §六-3 参数集中"""
import os, sys, importlib
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
for k in ['HTTP_PROXY', 'HTTPS_PROXY', 'ALL_PROXY']:
    os.environ.pop(k, None)

print("=== #8 tushare_provider 死段删除 ===")
import inspect
from app.data.tushare_provider import TushareProvider
src = inspect.getsource(TushareProvider)
for m in ('get_index_daily', 'get_stk_limit', 'get_moneyflow', 'get_top_list', 'get_top_inst', 'get_daily_basic'):
    n = src.count(f'def {m}(')
    print(f"  def {m}: {n} 处（期望 1）")
print(f"  get_daily_basic 使用 as e: {'except Exception as e' in inspect.getsource(TushareProvider.get_daily_basic)}（期望 True）")

print()
print("=== Q3 MinuteDataManager 删除 ===")
try:
    importlib.import_module('app.data.minute_data_manager')
    print("  模块仍可导入（异常）")
except ModuleNotFoundError as e:
    print(f"  模块已删除 ✅ ({e})")
import subprocess
r = subprocess.run(['grep', '-rl', 'minute_data_manager', 'app'], capture_output=True, text=True)
print(f"  app/ 下残留引用文件: {r.stdout.strip() or '(无)'}")

print()
print("=== §六-3 参数集中（yaml 驱动，零行为变更）===")
from config import load_yaml
ts = load_yaml('data_sources.yaml')['rate_limits']['tushare']
print(f"  yaml rate_limits.tushare = {ts}")
import data_daemon as dd
checks = [('_TS_MIN_INTERVAL', dd._TS_MIN_INTERVAL, 0.2), ('_TS_CALL_TIMEOUT', dd._TS_CALL_TIMEOUT, 15.0),
          ('_TS_MINUTE_INTERVAL', dd._TS_MINUTE_INTERVAL, 60.0), ('_TS_MINUTE_CALL_TIMEOUT', dd._TS_MINUTE_CALL_TIMEOUT, 60.0)]
for name, got, exp in checks:
    print(f"  {name} = {got}（期望 {exp}）{'OK' if got == exp else 'FAIL'}")

print()
print("ALL_CHECKS_DONE")
