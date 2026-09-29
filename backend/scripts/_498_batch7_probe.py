"""498号 批次7 验证探针（只读）：§六-2 DATA_DIR 顺序 / #53 AKShare分钟日期 / #42 ok计数 / §六-3 参数集中"""
import os, sys, inspect
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
for k in ['HTTP_PROXY', 'HTTPS_PROXY', 'ALL_PROXY']:
    os.environ.pop(k, None)

print("=== §六-2 DATA_DIR 解析顺序 + §六-3 常量集中 ===")
import data_daemon as dd
print(f"  _PRIORITY_LEVELS = {dd._PRIORITY_LEVELS}（期望 HIGH3/NORMAL2/LOW1）")
print(f"  _RETENTION_MIN_DAYS = {dd._RETENTION_MIN_DAYS}（期望 1095/180/365）")
print(f"  _MARGIN_SHORT_RATIO/_CHECK_WINDOW/_BASE_DAYS = {dd._MARGIN_SHORT_RATIO}/{dd._MARGIN_CHECK_WINDOW}/{dd._MARGIN_BASE_DAYS}（期望 0.9/5/20）")
src = inspect.getsource(dd)
_dotenv_i = src.index('load_dotenv(dotenv_path)')
_setdefault_i = src.index("setdefault(\n    'DATA_DIR'") if "setdefault(\n    'DATA_DIR'" in src else src.index("setdefault('DATA_DIR'")
print(f"  load_dotenv 在 DATA_DIR setdefault 之前: {_dotenv_i < _setdefault_i}（期望 True）")

print()
print("=== #53 AKShare 分钟日期（不再传空串覆盖默认）===")
from app.data.akshare_provider import AkshareProvider
body = inspect.getsource(AkshareProvider.get_minute_data)
_lines = [ln for ln in body.split('\n') if not ln.strip().startswith('#')]
_code = '\n'.join(_lines)
print("  代码中不再用 `start_date or ''`:", "start_date or ''" not in _code, "（期望 True）")
print("  仅在显式提供时传 start_date:", "if start_date:" in _code, "（期望 True）")
print("  用 **kwargs 调用:", "stock_zh_a_hist_min_em(**_kw)" in _code, "（期望 True）")
# period 归一化验证
for f in ('1min', '5m', '15min', '60m', '30'):
    _p = str(f).strip().lower()
    if _p.endswith('min'): _p = _p[:-3]
    elif _p.endswith('m'): _p = _p[:-1]
    print(f"    period 归一: {f!r} -> {_p!r}")

print()
print("=== #42 backfill_1min ok 计数（仅取到数据才计）===")
from app.data import minute_backfill
b = inspect.getsource(minute_backfill.backfill_1min)
_b_lines = [ln for ln in b.split('\n') if not ln.strip().startswith('#')]
_b_code = '\n'.join(_b_lines)
print("  新增 got_data 门控:", "got_data" in _b_code, "（期望 True）")
print("  代码中 ok += 1 仅 1 处:", _b_code.count("ok += 1") == 1, "（期望 True）")

print()
print("ALL_CHECKS_DONE")
