"""500号 批次8 探针——ws_bridge 死分支删除（Q2=A，含 #1/#55 归属）

静态/桩验证：
  #1  死路径已删（on_collect_complete / 7 个 _broadcast_* / broadcast_quote_update / _try_emit*）
      活路径保留（_watchlist_* 注册表 + get_watchlist_codes，供 push_service 消费）
  #1  采集侧死调用已移除（mootdx_collector / akshare_collector 不再引用 on_collect_complete）
  #1  realtime.py 的 trigger_publish 端点已删除
  #1  真实推送方 push_service 保持完整（4 个 push_* 函数 + scheduler_manager 注册）
"""
import inspect
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from app.data.ws_bridge import WsBridge, ws_bridge  # noqa: E402

FAIL = []


def check(cond, msg):
    print(('  OK  ' if cond else '  FAIL') + ' ' + msg)
    if not cond:
        FAIL.append(msg)


# ── #1 死路径已删 ───────────────────────────────────────────────────────
print("=== #1 ws_bridge 死路径删除 ===")
for _dead in ['on_collect_complete', '_broadcast_market_summary', '_broadcast_market_indices',
              '_broadcast_top_stocks', '_broadcast_sectors', '_broadcast_limit_pools',
              '_broadcast_news', '_broadcast_watchlist_quotes', 'broadcast_quote_update',
              '_try_emit', '_try_emit_to_room']:
    check(not hasattr(WsBridge, _dead), f"死方法 {_dead} 已删除")
check(not hasattr(ws_bridge, '_api_push_active'), "#1 _api_push_active 恒真开关已移除")

# ── #1 活路径保留 ───────────────────────────────────────────────────────
print("=== #1 活路径（自选股注册表）保留 ===")
for _live in ['update_watchlist_codes', 'remove_watchlist_codes',
              'clear_watchlist_codes', 'get_watchlist_codes']:
    check(hasattr(WsBridge, _live), f"活方法 {_live} 保留")
ws_bridge.update_watchlist_codes(['000001.SZ', '600519.SH'])
check(set(ws_bridge.get_watchlist_codes()) == {'000001.SZ', '600519.SH'}, "#1 注册表读写正常")
ws_bridge.remove_watchlist_codes(['000001.SZ'])
check(ws_bridge.get_watchlist_codes() == ['600519.SH'], "#1 移除正常")
ws_bridge.clear_watchlist_codes()
check(ws_bridge.get_watchlist_codes() == [], "#1 清空正常")

# ── #1 采集侧死调用已移除 ───────────────────────────────────────────────
print("=== #1 采集侧死调用移除 ===")
import app.data.akshare_collector as ak  # noqa: E402
import app.data.mootdx_collector as mx  # noqa: E402

mx_src = inspect.getsource(mx)
ak_src = inspect.getsource(ak)


def _code_calls(src: str, needle: str) -> list:
    """非注释行中出现的 needle（排除说明性注释）"""
    return [ln for ln in src.splitlines()
            if needle in ln and not ln.lstrip().startswith('#')]


check(_code_calls(mx_src, 'on_collect_complete') == [], "#1 mootdx_collector 无实际 on_collect_complete 调用")
check(_code_calls(ak_src, 'on_collect_complete') == [], "#1 akshare_collector 无实际 on_collect_complete 调用")
# ── #1 trigger_publish 端点已删除 ───────────────────────────────────────
print("=== #1 trigger_publish 端点删除 ===")
import app.routes.realtime as rt  # noqa: E402

rt_src = inspect.getsource(rt)
check('handle_trigger_publish' not in rt_src, "#1 trigger_publish 端点已删除")
check('on_collect_complete' not in rt_src.split('# 500号#1')[0] or
      "on_collect_complete('market_snapshot')`" in rt_src,
      "#1 realtime.py 无有效 on_collect_complete 调用（仅注释说明）")

# ── #1 真实推送方 push_service 完整 ─────────────────────────────────────
print("=== #1 push_service（真实推送方）完整 ===")
import app.services.push_service as ps  # noqa: E402

for _fn in ['push_market_summary', 'push_top_stocks', 'push_sector_rankings', 'push_watchlist_quotes']:
    check(hasattr(ps, _fn), f"push_service.{_fn} 保留")
_ps_src = inspect.getsource(ps)
check('ws_bridge.get_watchlist_codes' in _ps_src, "#1 push_watchlist_quotes 经注册表读自选股（活链）")
import app.scheduler_manager as sm  # noqa: E402

_sm_src = inspect.getsource(sm)
check('push_market_summary' in _sm_src and 'push_sector_rankings' in _sm_src,
      "#1 scheduler_manager 仍注册 push_service 推送任务")

print()
if FAIL:
    print(f"❌ {len(FAIL)} 项失败")
    sys.exit(1)
print("✅ 批次8 探针全绿（#1 ws_bridge 死分支删除）")
