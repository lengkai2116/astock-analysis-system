# P4: ConflictArbiter 四级仲裁集成 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use compose:subagent (recommended) or compose:execute to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 将已完成的 ConflictArbiter（四级仲裁器）集成到策略分析 E12/E13 流程中，替换现有的"仅比方向异同"的朴素冲突检测。

**Architecture:** ConflictArbiter 已完成 129 行代码（结构优先→位置优先→量价验证→嵌套处理→Kronos前瞻），但未被任何业务逻辑调用。本计划将其挂接到 `strategy_analyze.py` 的五维卡5（factor维度）和E13交叉验证链中，需要将缠论中枢数据传入仲裁器。

**Tech Stack:** Python 3.10+, Flask, no new dependencies

---

## 文件分析

| 文件 | 现有内容 | 本计划改动 |
|:-----|:---------|:-----------|
| `backend/app/engine/framework/conflict_arbiter.py` | 129行完整仲裁器，包含5级仲裁 | 不改动（仅可能微调接口） |
| `backend/app/routes/strategy_analyze.py` | 已 import ConflictArbiter(L14)，但未调用 | 3处集成点（见下） |
| `backend/tests/test_conflict_arbiter.py` | 不存在 | 新建测试文件 |

## 当前关键函数对照

| 函数 | 位置 | 当前行为 | 目标 |
|:-----|:-----|:---------|:-----|
| `_build_factor_dimension()` | L392-418 | 简单两两比较信号方向，输出"一致/轻微分歧/严重分歧" | 改为调用 ConflictArbiter.arbitrate() |
| `_build_default_chains()` | L799-858 | 4条硬编码验证链（方向异同检测） | 改为用 ConflictArbiter 的仲裁日志填充 |
| `_build_dimension_relations()` | L738-776 | 维度间两两方向比较 | 保持独立，但使用 ConflictArbiter 结果增强 |
| `_build_dimension_relations_from_signals()` | L780-796 | 信号方向列表两两比较 | 保持独立，但使用 ConflictArbiter 结果增强 |
| `compute_for_stock()` (E12) | L460-566 | 组装五维，factor维度调用 `_build_factor_dimension` | 将 `_build_factor_dimension` 替换为 ConflictArbiter 调用 |
| `strategy_status_aggregate()` (E13) | L582-649 | 调用 `_build_dimension_relations` + 回退 `_build_default_chains` | 在验证链中加入 ConflictArbiter 仲裁结果 |

---

## 集成流程设计

```
E12 compute_for_stock():

  signals (各策略信号列表)
    │
    ├─ _build_chanlun_dimension()  → 提取中枢对象（zhongshu）
    │
    └─ ConflictArbiter.arbitrate(
           signals=signals,
           zhongshu=zhongshu_obj,
           market_context={'current_price': ...},
           kronos_result=kronos_result
       )
       │
       ├─ final_signal / final_confidence → factor dimension 核心
       ├─ arbitration_log → factor dimension 的详细冲突内容
       └─ details (bullish/bearish/total) → factor dimension 的冲突统计

E13 strategy_status_aggregate():

  verification_chains:
    ├─ 原 _build_default_chains() 保持（作为轻量版本）
    └─ + ConflictArbiter 仲裁日志作为补充证据链

  dimension_relations:
    └─ 原 _build_dimension_relations() 保持
        + ConflictArbiter 的 final_confidence 增强 relation 描述
```

---

## 任务分解

### Task 1: 集成 ConflictArbiter 到 E12 (factor dimension)

**Files:**
- Modify: `backend/app/routes/strategy_analyze.py:392-418` (`_build_factor_dimension`)
- Modify: `backend/app/routes/strategy_analyze.py:510-517` (E12 组装处)

**Interfaces:**
- Consumes: `ConflictArbiter.arbitrate(signals, zhongshu, market_context, kronos_result)` → `Dict`
- Produces: 增强的 factor dimension（含 arbitration_log 和仲裁详情）

- [ ] **Step 1: 理解 `_build_factor_dimension` 当前调用位置**

  在 `strategy_analyze.py` L517，factor dimension 的构建：
  ```python
  'factor': _build_factor_dimension(signals),
  ```

  需要在调用点之前获取 zhongshu 对象和 market_context。查看 `_build_chanlun_dimension` 函数以了解 zhongshu 对象从哪里来。

- [ ] **Step 2: 重构 `_build_factor_dimension` 为调用 ConflictArbiter**

  旧函数（约L392-418）：
  ```python
  def _build_factor_dimension(signals: List[Dict]) -> Dict:
      """从所有信号的相互关系构建卡5（冲突检测）"""
      conflicted_pairs = []
      driving = None
      for i, sa in enumerate(signals):
          for sb in signals[i+1:]:
              da = sa.get('signal', 'neutral')
              db = sb.get('signal', 'neutral')
              if da != db and da != 'neutral' and db != 'neutral':
                  conflicted_pairs.append({
                      'pair': f"{sa.get('strategy_name','?')}-vs-{sb.get('strategy_name','?')}",
                      'relation': '矛盾',
                      'detail': f"{da} vs {db}",
                  })
      if signals:
          driving = max(signals, key=lambda s: s.get('confidence', 0))
      if not conflicted_pairs:
          conflict_type = '一致'
      elif len(conflicted_pairs) == 1:
          conflict_type = '轻微分歧'
      else:
          conflict_type = '严重分歧'
      return {
          'direction': driving.get('signal', 'neutral') if driving else 'neutral',
          'confidence': round(driving.get('confidence', 0), 2) if driving else 0.0,
          'status_text': conflict_type,
          'conflict_type': conflict_type,
          'conflict_items': conflicted_pairs,
          'driving_factor': driving.get('strategy_name', '') if driving else '',
      }
  ```

  改为：
  ```python
  def _build_factor_dimension(signals: List[Dict], zhongshu=None,
                               market_context=None, kronos_result=None) -> Dict:
      """从所有信号的相互关系构建卡5（冲突检测）——使用 ConflictArbiter"""
      # 优先使用 ConflictArbiter 四级仲裁
      arbiter = ConflictArbiter()
      result = arbiter.arbitrate(
          signals=signals,
          zhongshu=zhongshu,
          market_context=market_context,
          kronos_result=kronos_result,
      )

      # 确定主驱动力（置信度最高的信号）
      driving = max(signals, key=lambda s: s.get('confidence', 0)) if signals else None

      # 从仲裁结果转换到 factor dimension 格式
      conflict_type_map = {
          'bullish': '一致' if result['details'].get('bearish', 0) == 0 else '分歧',
          'bearish': '一致' if result['details'].get('bullish', 0) == 0 else '分歧',
          'neutral': '中性',
      }
      n_bullish = result['details'].get('bullish', 0)
      n_bearish = result['details'].get('bearish', 0)
      if n_bullish > 0 and n_bearish > 0:
          conflict_type = '严重分歧' if n_bullish > 0 and n_bearish > 0 else '一致'
      elif n_bullish > 0 or n_bearish > 0:
          conflict_type = '一致'
      else:
          conflict_type = '中性'

      return {
          'direction': result['final_signal'],
          'confidence': result['final_confidence'],
          'status_text': conflict_type,
          'conflict_type': conflict_type,
          'conflict_items': [
              {'pair': f"看涨({n_bullish}) vs 看空({n_bearish})",
               'relation': '矛盾', 'detail': step}
              for step in result['arbitration_log']
          ],
          'driving_factor': driving.get('strategy_name', '') if driving else '',
          'arbitration_log': result['arbitration_log'],
      }
  ```

- [ ] **Step 3: 修改 E12 中 factor dimension 的调用点**

  在 `strategy_analyze.py` L510-517，修改 factor dimension 的构建，传入 zhongshu 和 kronos：

  当前代码(L517)：
  ```python
  'factor': _build_factor_dimension(signals),
  ```

  改为：
  ```python
  # 从 chanlun dimension 提取中枢对象用于仲裁
  zhongshu_obj = None
  if chanlun_sig:
      cl_detail = chanlun_sig.get('chanlun_analysis_detail', {})
      zhongshu_obj = cl_detail.get('zhongshu') if isinstance(cl_detail, dict) else None

  'factor': _build_factor_dimension(
      signals,
      zhongshu=zhongshu_obj,
      market_context={'current_price': _get_latest_close(signals)},
      kronos_result=kronos_result,
  ),
  ```

  添加辅助函数 `_get_latest_close`：
  ```python
  def _get_latest_close(signals: List[Dict]) -> Optional[float]:
      """从策略信号中提取最新收盘价"""
      for s in signals:
          close = s.get('latest_close')
          if close is not None:
              return float(close)
      return None
  ```

### Task 2: 集成 ConflictArbiter 到 E13 (交叉验证链)

**Files:**
- Modify: `backend/app/routes/strategy_analyze.py:612-640` (E13 端点)

**Interfaces:**
- Consumes: ConflictArbiter result from signals + zhongshu
- Produces: 增强的 verification_chains 和 dimension_relations

- [ ] **Step 1: 在 E13 端点中添加 ConflictArbiter 调用**

  在 E13 端点（L612-640），在构建 chains 之前加入 ConflictArbiter 仲裁：

  当前逻辑（L612-625）：
  ```python
  sos = StatusOutputService()
  aggregated = sos.aggregate_v2(signals, market_state)
  if dimensions:
      dimension_relations = _build_dimension_relations(dimensions)
  else:
      dimension_relations = _build_dimension_relations_from_signals(signals)
  chains = aggregated.get('verification_chains', aggregated.get('chains', []))
  if not chains:
      chains = _build_default_chains(signals)
  ```

  改为：
  ```python
  sos = StatusOutputService()
  aggregated = sos.aggregate_v2(signals, market_state)
  if dimensions:
      dimension_relations = _build_dimension_relations(dimensions)
  else:
      dimension_relations = _build_dimension_relations_from_signals(signals)
  chains = aggregated.get('verification_chains', aggregated.get('chains', []))
  if not chains:
      chains = _build_default_chains(signals)

  # 加入 ConflictArbiter 仲裁结果作为补充证据链
  arbiter = ConflictArbiter()
  arbiter_result = arbiter.arbitrate(signals)  # 无中枢时仅做级别1/3/4/5
  if arbiter_result.get('arbitration_log'):
      chains.append({
          'id': 'arbitration',
          'name': '四级仲裁验证',
          'passed': arbiter_result['final_signal'] != 'neutral',
          'evidence': '; '.join(arbiter_result['arbitration_log'][-2:]),
          'confidence_multiplier': arbiter_result['final_confidence'],
          'conflict_detail': f"终裁: {arbiter_result['final_signal']}(置信度{arbiter_result['final_confidence']:.2f})",
      })
  ```

### Task 3: 编写测试

**Files:**
- Create: `backend/tests/test_conflict_arbiter_integration.py`

- [ ] **Step 1: 创建测试文件**

```python
"""测试 ConflictArbiter 集成到 strategy_analyze.py 后的行为"""

import json
from app.engine.framework.conflict_arbiter import ConflictArbiter


def test_conflict_arbiter_imported():
    """验证 ConflictArbiter 可导入"""
    assert ConflictArbiter is not None


def test_arbitrate_all_bullish():
    """全看涨信号 → final_signal=bullish"""
    arbiter = ConflictArbiter()
    signals = [
        {'strategy_name': '缠论走势分析', 'signal': 'bullish', 'confidence': 0.8},
        {'strategy_name': '量价分析策略', 'signal': 'bullish', 'confidence': 0.7},
        {'strategy_name': '筹码主力分析', 'signal': 'bullish', 'confidence': 0.6},
    ]
    result = arbiter.arbitrate(signals)
    assert result['final_signal'] == 'bullish'
    assert result['final_confidence'] >= 0.6
    assert 'arbitration_log' in result


def test_arbitrate_all_bearish():
    """全看跌信号 → final_signal=bearish"""
    arbiter = ConflictArbiter()
    signals = [
        {'strategy_name': '缠论走势分析', 'signal': 'bearish', 'confidence': 0.8},
        {'strategy_name': '量价分析策略', 'signal': 'bearish', 'confidence': 0.7},
    ]
    result = arbiter.arbitrate(signals)
    assert result['final_signal'] == 'bearish'
    assert result['final_confidence'] >= 0.6


def test_arbitrate_chanlun_overrides():
    """缠论 vs 其他：结构优先 — 最终信号应偏向缠论"""
    arbiter = ConflictArbiter()
    signals = [
        {'strategy_name': '缠论走势分析', 'signal': 'bullish', 'confidence': 0.6},
        {'strategy_name': '筹码主力分析', 'signal': 'bearish', 'confidence': 0.8},
        {'strategy_name': 'BOCIASI快线', 'signal': 'bearish', 'confidence': 0.7},
    ]
    result = arbiter.arbitrate(signals)
    # 缠论优先级1，筹码优先级3，缠论权重更高
    log_text = ' '.join(result.get('arbitration_log', []))
    assert '结构优先' in log_text


def test_arbitrate_empty():
    """空信号列表 → neutral"""
    arbiter = ConflictArbiter()
    result = arbiter.arbitrate([])
    assert result['final_signal'] == 'neutral'
    assert result['final_confidence'] == 0.0


def test_arbitrate_kronos_boost():
    """Kronos 确认多数方向 → 置信度增强"""
    arbiter = ConflictArbiter()
    signals = [
        {'strategy_name': '缠论走势分析', 'signal': 'bullish', 'confidence': 0.6},
        {'strategy_name': '量价分析策略', 'signal': 'bullish', 'confidence': 0.7},
    ]
    kronos = {'direction': 'bullish', 'confidence': 0.8, 'volatility_regime': 'normal'}
    result = arbiter.arbitrate(signals, kronos_result=kronos)
    log_text = ' '.join(result.get('arbitration_log', []))
    assert 'Kronos' in log_text
    assert '置信度增强' in log_text
```

- [ ] **Step 2: Run tests to verify**

  ```bash
  python backend/tests/test_conflict_arbiter_integration.py -v
  ```

  Expected: All tests PASS.

### Task 4: 验证集成

- [ ] **Step 1: 运行 lint 检查**

  ```bash
  make lint
  ```

  Expected: No new lint errors.

- [ ] **Step 2: 运行类型检查**

  ```bash
  make typecheck
  ```

  Expected: No new type errors.

- [ ] **Step 3: 运行全套测试**

  ```bash
  make test
  ```

  Expected: All tests pass (including existing tests).

---

## 自检

1. **Spec coverage:** P4 covers integrating ConflictArbiter into both E12 and E13. All code paths in the file are covered.
2. **Placeholder scan:** No TBD or placeholder content.
3. **Type consistency:** `ConflictArbiter.arbitrate()` signature matches the call sites. Return type `Dict` with `final_signal`, `final_confidence`, `arbitration_log`, `details` is consistent across all uses.
