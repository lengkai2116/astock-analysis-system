# 全市场策略预计算 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use compose:subagent (recommended) or compose:execute to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 实现 UnifiedStrategyCore 统一核心层，建立全市场盘后预计算 + 策略信号缓存体系

**Architecture:** 
- 新建 `UnifiedStrategyCore` 作为唯一策略计算入口，封装现有 `SignalComputationService.compute_for_stock()`
- 新建 `strategy_signal_detail` 表存储完整 signal dict JSON，替代现有 `strategy_signals` 简化表
- daemon 日终预计算写入新表，路由层读取缓存加速 100x
- DeepSeek 从策略分析端点分离为独立用户触发端点

**Tech Stack:** Python 3.10+, Flask, SQLite, pandas

## Global Constraints

- 所有非采集层代码禁止实例化数据源 Provider
- DataManager 是存储层唯一网关
- 禁止 use_cache=False
- 文件路径用 pathlib.Path
- 文件读写指定 encoding='utf-8'

---

### Task 1: UnifiedStrategyCore 核心类

**Files:**
- Create: `backend/app/engine/unified_core.py`
- Test: `backend/tests/test_unified_core.py`

**Interfaces:**
- Produces: `UnifiedStrategyCore.compute(ts_code, period) -> StandardizedResult`
- Produces: `UnifiedStrategyCore.compute_batch(ts_codes) -> dict[str, StandardizedResult]`

- [ ] **Step 1: 创建 StandardizedResult 数据类**

```python
# backend/app/engine/unified_core.py
from dataclasses import dataclass, field, asdict
from typing import Optional

@dataclass
class StrategySignal:
    """单个策略的标准化输出"""
    strategy_name: str
    raw_score: float = 0.0          # 0-1 或 0-10 原始分
    direction: str = 'neutral'      # bullish/bearish/neutral
    confidence: float = 0.0         # 置信度 0-1
    signal: str = 'NEUTRAL'         # BULLISH/BEARISH/NEUTRAL/WATCH
    signal_label: str = ''          # 中文标签
    evidence: list = field(default_factory=list)  # 依据文本
    status_recognition: dict = field(default_factory=dict)  # 完整状态识别
    raw_detail: dict = field(default_factory=dict)  # 完整策略细节

@dataclass
class StandardizedResult:
    """统一策略计算结果"""
    ts_code: str
    trade_date: str
    period: str = 'long'
    signals: dict[str, StrategySignal] = field(default_factory=dict)  # key=策略名
    market_context: dict = field(default_factory=dict)
    data_availability: dict = field(default_factory=dict)
    
    def to_dict(self) -> dict:
        return asdict(self)
    
    @classmethod
    def from_dict(cls, d: dict) -> 'StandardizedResult':
        signals = {}
        for k, v in d.get('signals', {}).items():
            signals[k] = StrategySignal(**v)
        d['signals'] = signals
        return cls(**d)
```

- [ ] **Step 2: 实现 UnifiedStrategyCore.compute()**

核心思路：将 `SignalComputationService.compute_for_stock()` 返回的 List[Dict] 转换为 StandardizedResult。

```python
# backend/app/engine/unified_core.py (续)

class UnifiedStrategyCore:
    """统一策略核心——所有策略计算的唯一入口"""
    
    def compute(self, ts_code: str, period: str = 'long') -> StandardizedResult:
        from app.services.signal_computation_service import SignalComputationService
        scs = SignalComputationService()
        signals = scs.compute_for_stock(ts_code, period=period)
        return self._to_standardized(ts_code, signals, period, scs)
    
    def _to_standardized(self, ts_code, signals, period, scs=None) -> StandardizedResult:
        today = datetime.now().strftime('%Y%m%d')
        signal_map = {
            '缠论': 'chanlun', '量价': 'volume_price', '筹码': 'chip',
            'BOCIASI': 'bociasi', '因子': 'factor', 'Vibe': 'vibe',
        }
        result_signals = {}
        for sig in signals:
            name = sig.get('strategy_name', '')
            key = signal_map.get(name, name)
            status = sig.get('status_recognition') or {}
            result_signals[key] = StrategySignal(
                strategy_name=name,
                raw_score=sig.get('confidence', 0) if isinstance(sig.get('confidence'), (int, float)) else 0,
                direction=sig.get('signal', 'neutral'),
                confidence=sig.get('confidence', 0) if isinstance(sig.get('confidence'), (int, float)) else 0,
                signal=sig.get('signal_level', 'NEUTRAL') or sig.get('signal', 'NEUTRAL'),
                signal_label=sig.get('signal_label', ''),
                evidence=sig.get('evidence', []),
                status_recognition=status,
                raw_detail={k: v for k, v in sig.items() if k not in ('strategy_name', 'confidence', 'signal', 'signal_level', 'evidence', 'status_recognition', 'signal_label')},
            )
        da = scs.last_data_availability if scs and hasattr(scs, 'last_data_availability') else {}
        return StandardizedResult(
            ts_code=ts_code, trade_date=today, period=period,
            signals=result_signals, data_availability=da,
        )
    
    def compute_batch(self, ts_codes: list[str], period: str = 'long', max_workers: int = 4) -> dict[str, StandardizedResult]:
        import concurrent.futures
        results = {}
        with concurrent.futures.ThreadPoolExecutor(max_workers=max_workers) as exe:
            fut_map = {exe.submit(self._safe_compute, code, period): code for code in ts_codes}
            for fut in concurrent.futures.as_completed(fut_map):
                code = fut_map[fut]
                try:
                    res = fut.result()
                    if res:
                        results[code] = res
                except Exception:
                    continue
        return results
    
    def _safe_compute(self, ts_code: str, period: str) -> Optional[StandardizedResult]:
        try:
            return self.compute(ts_code, period=period)
        except Exception:
            return None
```

- [ ] **Step 3: 创建单元测试**

```python
# backend/tests/test_unified_core.py
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

def test_standardized_result_serde():
    from app.engine.unified_core import StandardizedResult, StrategySignal
    sr = StandardizedResult(
        ts_code='000001.SZ',
        trade_date='20260722',
        signals={'chanlun': StrategySignal(strategy_name='缠论', raw_score=7.5, direction='bullish')}
    )
    d = sr.to_dict()
    assert d['ts_code'] == '000001.SZ'
    assert d['signals']['chanlun']['raw_score'] == 7.5
    restored = StandardizedResult.from_dict(d)
    assert restored.signals['chanlun'].raw_score == 7.5
    assert restored.signals['chanlun'].direction == 'bullish'
    print("✅ test_standardized_result_serde PASSED")

def test_unified_core_import():
    from app.engine.unified_core import UnifiedStrategyCore
    assert UnifiedStrategyCore is not None
    print("✅ test_unified_core_import PASSED")

if __name__ == '__main__':
    test_standardized_result_serde()
    test_unified_core_import()
```

- [ ] **Step 4: 验证单元测试通过**

Run: `python backend/tests/test_unified_core.py`

Expected:
```
✅ test_standardized_result_serde PASSED
✅ test_unified_core_import PASSED
```

---

### Task 2: 缓存层 strategy_signal_detail 表 + ECM 方法

**Files:**
- Modify: `backend/app/data/enhanced_cache_manager.py`
- Modify: `backend/app/data/__init__.py`

**Interfaces:**
- Consumes: `StandardizedResult.to_dict()` (from Task 1)
- Produces: `ECM.cache_signal_detail(ts_code, result_dict)`
- Produces: `ECM.get_signal_detail(ts_code) -> dict | None`

- [ ] **Step 1: 在 ECM 中添加 strategy_signal_detail 建表 + 读写方法**

在 `enhanced_cache_manager.py` 的 `setup_database()` 中，在 strategy_signals 表创建之后添加新表：

```python
# 在策略信号表 strategy_signals 之后添加
self._execute("""
    CREATE TABLE IF NOT EXISTS strategy_signal_detail (
        ts_code TEXT NOT NULL,
        trade_date TEXT NOT NULL,
        signal_json TEXT NOT NULL,
        schema_version INTEGER DEFAULT 1,
        cached_at TEXT DEFAULT (datetime('now','localtime')),
        PRIMARY KEY (ts_code, trade_date)
    )
""")
```

新增方法：

```python
def cache_signal_detail(self, ts_code: str, result_dict: dict):
    """缓存完整策略信号详情（替代 cache_strategy_signals）"""
    trade_date = result_dict.get('trade_date', datetime.now().strftime('%Y%m%d'))
    import json
    signal_json = json.dumps(result_dict, ensure_ascii=False, default=str)
    with self._write_lock:
        try:
            self._execute(
                """INSERT OR REPLACE INTO strategy_signal_detail 
                   (ts_code, trade_date, signal_json, schema_version, cached_at)
                   VALUES (?, ?, ?, 1, datetime('now','localtime'))""",
                [ts_code, trade_date, signal_json]
            )
        except Exception as e:
            logger.warning(f"缓存信号详情失败 [{ts_code}]: {e}")

def get_signal_detail(self, ts_code: str, trade_date: str = None) -> Optional[dict]:
    """读取缓存策略信号详情"""
    if trade_date is None:
        trade_date = datetime.now().strftime('%Y%m%d')
    try:
        row = self._fetchone(
            "SELECT signal_json FROM strategy_signal_detail WHERE ts_code=? AND trade_date=?",
            [ts_code, trade_date]
        )
        if row:
            import json
            data = json.loads(row[0])
            if data.get('schema_version', 1) != 1:
                return None  # 版本不匹配，跳过缓存
            return data
    except Exception:
        pass
    return None

def has_signal_detail(self, ts_code: str, trade_date: str = None) -> bool:
    """检查是否存在缓存"""
    if trade_date is None:
        trade_date = datetime.now().strftime('%Y%m%d')
    try:
        row = self._fetchone(
            "SELECT 1 FROM strategy_signal_detail WHERE ts_code=? AND trade_date=?",
            [ts_code, trade_date]
        )
        return row is not None
    except Exception:
        return False
```

- [ ] **Step 2: 通过 DataManager 暴露接口**

在 `backend/app/data/__init__.py` 的 DataManager 类中添加：

```python
def cache_signal_detail(self, ts_code: str, result_dict: dict):
    from app.data.enhanced_cache_manager import get_ecm_instance
    ecm = get_ecm_instance()
    ecm.cache_signal_detail(ts_code, result_dict)

def get_signal_detail(self, ts_code: str, trade_date: str = None) -> Optional[dict]:
    from app.data.enhanced_cache_manager import get_ecm_instance
    ecm = get_ecm_instance()
    return ecm.get_signal_detail(ts_code, trade_date)

def has_signal_detail(self, ts_code: str, trade_date: str = None) -> bool:
    from app.data.enhanced_cache_manager import get_ecm_instance
    ecm = get_ecm_instance()
    return ecm.has_signal_detail(ts_code, trade_date)
```

---

### Task 3: Daemon 预计算接入 UnifiedStrategyCore

**Files:**
- Modify: `backend/data_daemon.py`
- Modify (删除): `backend/app/services/signal_computation_service.py` 中的 `cache_strategy_signals` 调用

- [ ] **Step 1: 修改 `_run_precompute()` 中的策略信号预计算部分**

将策略信号预计算改为：
1. 调用 `UnifiedStrategyCore.compute_batch()`
2. 写入 `strategy_signal_detail` 表（新表单表统一存储）
3. 不再写入 `strategy_signals` 表

```python
# 在 _run_precompute() 中替换"策略信号预计算"部分:

    # 2) 策略信号全市场预计算（UnifiedStrategyCore）
    try:
        from app.engine.unified_core import UnifiedStrategyCore
        core = UnifiedStrategyCore()
        results = core.compute_batch(codes, max_workers=4)
        count = 0
        for ts_code, result in results.items():
            try:
                _ecm.cache_signal_detail(ts_code, result.to_dict())
                count += 1
            except Exception:
                continue
        logger.info(f"策略信号预计算完成: {count}/{len(codes)} 只 (UnifiedStrategyCore)")
    except Exception as e:
        logger.warning(f"策略信号预计算整体失败: {e}")
```

- [ ] **Step 2: 删除旧的 strategy_signals 写入逻辑**

删除 `_run_precompute()` 中原来调用 `SignalComputationService` 和 `_ecm.cache_strategy_signals()` 的旧代码块。

---

### Task 4: Strategy Analyze 路由接入缓存 + DeepSeek 分离

**Files:**
- Modify: `backend/app/routes/strategy_analyze.py`

- [ ] **Step 1: 修改 strategy_analyze() 优先读取缓存**

```python
# 在 strategy_analyze() 的 Step 1 之前添加缓存检查:

# Step 0: 尝试从缓存读取
dm = DataManager()
cached = dm.get_signal_detail(ts_code)
if cached:
    signals = cached.get('signals', {})
    data_availability = cached.get('data_availability', {})
    # 将 signals dict 转回 List[Dict] 兼容下游 _find_signal
    # 但更好的方式是直接构建 dimensions...
else:
    # 实时计算
    scs = SignalComputationService()
    signals = scs.compute_for_stock(ts_code, period=period)
    data_availability = scs.last_data_availability
```

但这里 refactoring 比较复杂，因为下游 `_build_*_dimension()` 函数接受 signal dict（从 `List[Dict]` 中 `_find_signal` 提取），不是直接接受 StandardizedResult。

`_find_signal` 函数：
```python
def _find_signal(signals, name):
    for s in signals:
        if name in s.get('strategy_name', ''):
            return s
    return None
```

标准的 signal dict 长什么样子？从 StrategyOutput.to_dict() 看应该是：
```python
{
    'strategy_name': '缠论走势分析',
    'signal': 'bullish',
    'confidence': 0.75,
    'signal_label': '',
    'signal_date': '20260722',
    'status_recognition': {...},
    'chanlun_analysis_detail': {...},
    'evidence': [...],
    'entry_zone_low/ high': ...,
    'risk_line': ...,
    'target_zone_low/ high': ...,
    'backtest_win_rates': ...,
    ...
}
```

所以缓存读取后，需要从 cached['signals'] 中恢复这个 List[Dict] 格式。

```python
# 将缓存的 signals dict 恢复为 List[Dict]
signals_list = []
for key, sig in cached.get('signals', {}).items():
    sig_dict = sig.get('raw_detail', {})
    sig_dict.update({
        'strategy_name': sig.get('strategy_name', ''),
        'signal': sig.get('direction', 'neutral'),
        'confidence': sig.get('confidence', 0),
        'signal_level': sig.get('signal', 'NEUTRAL'),
        'signal_label': sig.get('signal_label', ''),
        'evidence': sig.get('evidence', []),
        'status_recognition': sig.get('status_recognition', {}),
    })
    signals_list.append(sig_dict)
```

- [ ] **Step 2: 移除 DeepSeek 文本从 E12 响应**

```python
# 移除 strategy_analyze() 中的:
# deepseek_text = _get_deepseek_status_text(ts_code)
# if deepseek_text:
#     dimensions['chanlun']['deepseek_text'] = deepseek_text
#     dimensions['chanlun']['status_text'] = deepseek_text

# 改为:
dimensions = _build_all_dimensions(...)  # 不含 DeepSeek
# 可选: NLG 规则生成的现状文本仍在 status_recognition 中
```

- [ ] **Step 3: 新增 DeepSeek 独立端点**

```python
@strategy_analyze_bp.route('/api/v3/strategy/deepseek', methods=['GET'])
def strategy_deepseek():
    """用户触发的 DeepSeek 九层描述生成"""
    ts_code = request.args.get('ts_code', '').strip()
    if not ts_code:
        return jsonify({'code': -1, 'message': 'ts_code必填'}), 400
    
    # 从缓存读取信号数据
    dm = DataManager()
    cached = dm.get_signal_detail(ts_code)
    if not cached:
        return jsonify({'code': -1, 'message': '策略信号未就绪，请稍后重试'}), 503
    
    # 构建 DeepSeek 上下文
    text = _get_deepseek_status_text(ts_code)
    if not text:
        return jsonify({'code': -1, 'message': 'DeepSeek 不可用（请检查 LLM 配置）'}), 503
    
    return jsonify({'code': 0, 'data': {'ts_code': ts_code, 'deepseek_text': text}})
```

---

### Task 5: Screener L3 适配

**Files:**
- Modify: `backend/app/engine/framework/screener_strategy_integration.py`

- [ ] **Step 1: screen_l3_candidates 接入 UnifiedStrategyCore**

在 `screen_l3_candidates()` 的阶段一内部，对每只候选股使用 UnifiedStrategyCore 替代当前分散计算调用。

```python
# 在阶段一计算原始分时:
from app.engine.unified_core import UnifiedStrategyCore
core = UnifiedStrategyCore()
result = core.compute(candidate['ts_code'])
signals = result.signals

# 提取各策略 raw_score
chanlun_score = signals.get('chanlun', {}).get('raw_score', 0)
volume_price_score = signals.get('volume_price', {}).get('raw_score', 0)
factor_score = signals.get('factor', {}).get('raw_score', 0)
bociasi_score = signals.get('bociasi', {}).get('raw_score', 0)
```

- [ ] **Step 2: 删除 _FACTOR_COMPUTERS 及相关注册代码**

删除或清空 `_FACTOR_COMPUTERS` 字典、`_register_factor`、`_register_ecm_factor` 及所有注册的因子函数（约 600 行）。

- [ ] **Step 3: 保留 _adjust_score_with_context 在选股适配器中**

确认 `_adjust_score_with_context` 仍保留在文件中，在阶段三综合评分后调用。

---

### Task 6: SignalComputationService 废弃处理

**Files:**
- Delete: `backend/app/services/signal_computation_service.py`

- [ ] **Step 1: 检查所有引用**

搜索所有 from/import `SignalComputationService` 的引用：
- `data_daemon.py` — 需替换（在 Task 3 中处理）
- `strategy_analyze.py` — 需替换（在 Task 4 中处理）
- 其他文件 — 确认无引用

- [ ] **Step 2: 删除文件**

确认无引用后删除 `backend/app/services/signal_computation_service.py`。

---

### Task 7: 实施计划汇总

| 步骤 | 内容 | 优先级 | 前置条件 |
|:-----|:-----|:-------|:---------|
| T1 | UnifiedStrategyCore 核心类 | P0 | — |
| T2 | 缓存层 strategy_signal_detail 表 + ECM 方法 | P0 | T1 |
| T3 | Daemon 预计算接入 | P1 | T1 + T2 |
| T4 | Strategy Analyze 路由接入缓存 + DeepSeek 分离 | P1 | T1 + T2 |
| T5 | Screener L3 适配 | P2 | T1 |
| T6 | SignalComputationService 废弃 | P3 | T1-T5 |

当前焦点：**T1 → T2 → T3**
