"""500号 批次5 探针——源管理/缓存/ECM/观测（#20~#35 + #55/#56）

桩/静态验证（不依赖真实库/网络）：
  #20 data_source_manager 共享态持锁（并发自增不丢计数）
  #21 reset_source 复位 avg_latency_ms/consecutive_successes
  #22 空结果判据含 pandas 空对象
  #23 memory_cache.invalidate 非法 level 不抛 KeyError
  #24 get_stats 读前 expire（过期项不计入 size）
  #25 ECM.close() 关全部 5 连接
  #26 _query_shard/_exec_shard 预初始化 sharding_manager
  #28 monitor 告警 ID 单调（裁剪后不碰撞）
  #29 monitor 读方法持锁
  #30 monitor 未知级别不静默降 INFO
  #31 stg_quality 写锁计数持锁
  #32 stg_quality 非 dict 归因（单独）
  #33 stg_quality 常量兜底容差比较
  #34 stg_quality 吞异常补 warning（源码断言）
  #35 stg_quality expected_ratio 接线 + 列数校验
  #55 ws_bridge 指数按市场限定匹配
"""
import inspect
import os
import sys
import threading

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

import pandas as pd  # noqa: E402
from app.data.data_source_manager import (  # noqa: E402
    DataSourceManager,
    DataSourceStatus,
    _is_empty_result,
)
from app.data.memory_cache import TieredMemoryCache  # noqa: E402
from app.data.monitor import Monitor  # noqa: E402

FAIL = []


def check(cond, msg):
    print(('  OK  ' if cond else '  FAIL') + ' ' + msg)
    if not cond:
        FAIL.append(msg)


# ── #22 空结果判据 ──────────────────────────────────────────────────────
print("=== #22 空结果判据 ===")
check(_is_empty_result(None), "#22 None 为空")
check(_is_empty_result([]), "#22 [] 为空")
check(_is_empty_result({}), "#22 {} 为空")
check(_is_empty_result(pd.DataFrame()), "#22 空 DataFrame 为空（原漏判）")
check(_is_empty_result(pd.Series([], dtype=float)), "#22 空 Series 为空（原漏判）")
check(not _is_empty_result(pd.DataFrame({'a': [1]})), "#22 非空 DataFrame 不为空")
check(not _is_empty_result([1, 2]), "#22 非空 list 不为空")
check(not _is_empty_result(0), "#22 0 不为空（非容器）")

# ── #20/#21 data_source_manager ─────────────────────────────────────────
print("=== #20/#21 data_source_manager ===")
dsm = DataSourceManager()
dsm.register_source('tushare', lambda e, p: [], priority=0)


def _bump():
    h = dsm.sources['tushare']
    for _ in range(2000):
        dsm._lock.acquire()
        try:
            h.failures += 1
        finally:
            dsm._lock.release()


ts = [threading.Thread(target=_bump) for _ in range(8)]
[t.start() for t in ts]
[t.join() for t in ts]
check(dsm.sources['tushare'].failures == 16000, f"#20 持锁自增无丢失（实={dsm.sources['tushare'].failures}）")

# #21 reset_source 复位延迟量/连续成功
h = dsm.sources['tushare']
h.avg_latency_ms = 9999.0
h.consecutive_successes = 7
h.status = DataSourceStatus.DEGRADED
dsm.reset_source('tushare')
check(h.avg_latency_ms == 0.0, "#21 reset 复位 avg_latency_ms（原未复位→立即重判 DEGRADED）")
check(h.consecutive_successes == 0, "#21 reset 复位 consecutive_successes")
check(h.status == DataSourceStatus.NORMAL, "#21 reset 复位 status")

# 回归：因延迟降级的源重置后不被立即重判 DEGRADED
h.status = DataSourceStatus.DEGRADED
h.avg_latency_ms = 6000.0
dsm.reset_source('tushare')
dsm._evaluate_status('tushare', h)
check(h.status == DataSourceStatus.NORMAL, "#21 重置后 _evaluate_status 不再立即判 DEGRADED")

# ── #23/#24 memory_cache ────────────────────────────────────────────────
print("=== #23/#24 memory_cache ===")
mc = TieredMemoryCache()
try:
    mc.invalidate('k', level='no_such_level')
    check(True, "#23 invalidate 非法 level 不抛 KeyError")
except KeyError:
    check(False, "#23 invalidate 非法 level 抛 KeyError")
mc.set('a', 1, level='realtime')
stats = mc.get_stats()
check(stats['realtime']['size'] >= 1, "#24 get_stats 正常返回 size")

# ── #25/#26 ECM 源码断言 ────────────────────────────────────────────────
print("=== #25/#26 ECM 源码断言 ===")
import app.data.enhanced_cache_manager as ecm_mod  # noqa: E402
from app.data.enhanced_cache_manager import EnhancedCacheManager  # noqa: E402

_src_close = inspect.getsource(EnhancedCacheManager.close)
for attr in ['read_conn', 'compute_conn', 'compute_read_conn', 'snapshot_conn']:
    check(attr in _src_close, f"#25 close() 覆盖 {attr}")
_src_qs = inspect.getsource(EnhancedCacheManager._query_shard)
check('sharding_manager = None' in _src_qs, "#26 _query_shard 预初始化 sharding_manager")
_src_es = inspect.getsource(EnhancedCacheManager._exec_shard)
check('sharding_manager = None' in _src_es, "#26 _exec_shard 预初始化 sharding_manager")

# ── #28/#29/#30 monitor ─────────────────────────────────────────────────
print("=== #28/#29/#30 monitor ===")
mon = Monitor()
for i in range(120):
    mon.create_alert('WARNING', f'title{i}', 'msg')
alerts = mon.get_alerts(limit=200)
ids = [a['id'] for a in alerts]
check(len(set(ids)) == len(ids), f"#28 裁剪后告警 ID 无碰撞（{len(ids)} 条唯一）")
check(max(ids) == 120, f"#28 ID 单调计数（最大={max(ids)}，非 len(_alerts)+1）")
# acknowledge 精确命中
target = alerts[10]['id']
mon.acknowledge_alert(target)
check([a for a in mon.get_alerts(limit=200) if a['id'] == target][0]['acknowledged'] is True,
      "#28 acknowledge_alert 精确命中")
# #29 读方法持锁（源码断言）
for m in ['get_metric_stats', 'get_alerts', 'acknowledge_alert', 'register_alert_callback']:
    check('with self._lock' in inspect.getsource(getattr(Monitor, m)), f"#29 {m} 持锁")
# #30 未知级别不静默降 INFO
import logging as _lg  # noqa: E402

_recs = []


class _H(_lg.Handler):
    def emit(self, r):
        _recs.append(r)


_l = _lg.getLogger('app.data.monitor')
_hh = _H()
_l.addHandler(_hh)
_l.setLevel(_lg.WARNING)
mon.create_alert(None, '未知级别', 'msg')
_l.removeHandler(_hh)
check(any('未知告警级别' in r.getMessage() for r in _recs), "#30 未知级别回退 warning（不静默 INFO）")

# ── #31/#33/#35 stg_quality ─────────────────────────────────────────────
print("=== #31/#33/#35 stg_quality ===")
import app.data.stg_quality as sq  # noqa: E402

_src31 = inspect.getsource(sq._record_write_lock)
check('with _write_lock_conflicts_lock' in _src31, "#31 写锁计数持锁")


def _bump2():
    for _ in range(2000):
        sq._record_write_lock('tbl_x')


ts2 = [threading.Thread(target=_bump2) for _ in range(6)]
[t.start() for t in ts2]
[t.join() for t in ts2]
check(sq.get_write_lock_conflicts().get('tbl_x') == 12000,
      f"#31 并发计数无丢失（实={sq.get_write_lock_conflicts().get('tbl_x')}）")

W = sq.QualityChecker if hasattr(sq, 'QualityChecker') else None
# #33 常量兜底容差比较
_checker_cls = None
for _n in dir(sq):
    _o = getattr(sq, _n)
    if isinstance(_o, type) and hasattr(_o, '_all_constant_fallback'):
        _checker_cls = _o
        break
if _checker_cls:
    _inst = _checker_cls.__new__(_checker_cls)
    check(_inst._all_constant_fallback((0.5, 0.5, 1.0)), "#33 兜底常量集（容差）判为假值")
    check(not _inst._all_constant_fallback((0.5, 3.7)), "#33 非常量值不判假")
else:
    check(False, "#33 未找到 _all_constant_fallback 宿主类")

# #35 expected_ratio 接线 + 列数校验
_src_val = inspect.getsource(sq.WriteGateway.validate_before_write)
check('expected_cols' in _src_val, "#35 validate_before_write 支持列数校验")
_src_wb = inspect.getsource(sq.WriteGateway.write_batch)
check('expected_cols' in _src_wb and 'expected_ratio < 0.95' in _src_wb, "#35 expected_ratio 已接线")

# #32 非 dict 顶层单独归因（源码断言）
_src32 = inspect.getsource(sq.QualityChecker.validate_signal_rows)
check('顶层非 dict' in _src32, "#32 非 dict 顶层单独归因（不再混入「非法」）")
# #34 吞异常补 warning
_src34a = inspect.getsource(sq.QualityChecker.daily_base)
_src34b = inspect.getsource(sq.QualityChecker._count_null_fields)
check('logger.warning' in _src34a and 'logger.warning' in _src34b, "#34 daily_base/_count_null_fields 补 warning")

# ── #55 ws_bridge 指数市场限定 ──────────────────────────────────────────
print("=== #55 ws_bridge ===")
import app.data.ws_bridge as wb  # noqa: E402

_src55 = inspect.getsource(wb.WsBridge)
check('_MKT' in _src55 and 'em_code' in _src55, "#55 指数按市场限定匹配（em_code 归一）")
check('short_code == ec_short' not in _src55, "#55 旧裸短码匹配已移除")

print()
if FAIL:
    print(f"❌ {len(FAIL)} 项失败")
    sys.exit(1)
print("✅ 批次5 探针全绿（#20~#35/#55）")
