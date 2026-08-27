---
title: Phase 1 - 第7维状态总结基础增强
type: 实施方案（子方案）
date: 2026-08-21
version: v1.0
parent: 364-七维现状描述系统实施方案（总纲）
status: 已废弃——369号维度引擎整合后，dim8_summary_engine已替代本方案Phase1功能
---

# 364a - Phase 1：第7维状态总结基础增强（8h）

> 目标：为七维模板增加audit（条件稽核）、judgment（独立判定）、plain（动态白话）三大核心字段，并修复status_bar为5态。

---

## 一、当前代码状态

### 1.1 build_seven_dim_report() 当前实现（status_engine.py:608-654）

```python
# 当前输出结构（每段）
{
    'title': '信号确认状态',
    'light': '✅',           # emoji灯
    'text': '信号生命周期：中期',  # 简略描述
    'plain': '最近信号的介入贵贱'  # 硬编码占位
}
```

**问题**：
- 无`judgment`字段（结论判定与状态描述混在text中）
- 无`audit`字段（无条件稽核）
- `plain`为硬编码非动态
- 缺少summary_text和one_liner_detail字段

### 1.2 status_snapshot表结构（enhanced_cache_manager.py:774-789）

```sql
CREATE TABLE status_snapshot (
    ts_code TEXT PRIMARY KEY,
    snapshot_date TEXT,
    trade_date TEXT,
    dim_states TEXT,           -- 11维JSON
    status_bar TEXT,           -- 4态
    opportunity_state TEXT,
    state_evidence TEXT,
    conflict_evidence TEXT,
    consensus_rate REAL,
    direction TEXT,
    l0 TEXT,
    lifecycle TEXT,
    advice_params TEXT,
    created_at TEXT
)
```

**缺失字段**：summary_text, one_liner_detail

### 1.3 _status_bar() 当前实现（status_engine.py:535-546）

```python
def _status_bar(self, dims, state):
    green = sum(1 for d in dims.values() if d['light'] == 'green')
    red = sum(1 for d in dims.values() if d['light'] == 'red')
    if state == 'avoid':
        return '风险区'           # 应为'不可交易'
    if green >= 6:
        return '强趋势'
    if green >= 4:
        return '趋势确认'
    if red >= 4:
        return '趋势转弱'
    return '趋势确认'            # 缺少'持有观望'和'风险区'
```

---

## 二、修订内容

### 2.1 新建文件：condition_auditor.py ✅ 已完成

位置：`backend/app/opportunity_atlas/condition_auditor.py`

已实现6维度条件稽核器。

### 2.2 修改：build_seven_dim_report() 重构

**修改文件**：`backend/app/opportunity_atlas/status_engine.py`

**修改行号**：608-654（替换整个函数）

**新增输入参数**：`tags`（pre_feat_cache扁平化后的数据）

**输出结构变更**：

```python
# 新输出结构（每段）
{
    'title': '信号确认状态',
    'light': '✅',                    # emoji灯（保留）
    'judgment': '右侧确认',           # 新增：独立结论判定
    'audit': {                        # 新增：条件稽核
        'conditions': [
            {'name': '信号触发', 'satisfied': True, 'actual': '已触发', 'threshold': '需有活跃信号', 'detail': '...'},
            {'name': '信号验证', 'satisfied': True, 'actual': '初期', 'threshold': '初期或中期', 'detail': '...'},
            ...
        ],
        'satisfied_count': 4,
        'total_count': 4,
        'confidence': 1.0
    },
    'plain': '买入信号5天前触发，至今有效，3维共振确认'  # 修改：动态生成
}
```

**具体修改逻辑**：

```python
def build_seven_dim_report(snapshot_row: dict, tags: dict = None) -> dict:
    """364a Phase 1：七维现状描述模板（含audit+judgment+plain）"""
    import json as _json
    from app.opportunity_atlas.condition_auditor import audit_dimension
    
    try:
        dims = _json.loads(snapshot_row.get('dim_states') or '{}')
    except Exception:
        dims = {}
    
    st = snapshot_row.get('status_bar', '')
    state = snapshot_row.get('opportunity_state', 'wait')
    _l = {'green': '✅', 'yellow': '⚠️', 'red': '🚫'}
    tags = tags or {}
    
    def _seg(title, dim_key, light_source, text_fn, plain_fn, judgment_fn=None):
        """通用段落构建器"""
        audit_result = audit_dimension(dim_key, dims, tags, {}) if dim_key else {'conditions': [], 'satisfied_count': 0, 'total_count': 0, 'confidence': 0}
        return {
            'title': title,
            'light': _l.get(light_source, '⚠️'),
            'judgment': judgment_fn(dims, tags) if judgment_fn else '',
            'audit': audit_result,
            'text': text_fn(dims, tags),
            'plain': plain_fn(dims, tags)
        }
    
    # 各维度plain生成函数
    def _signal_plain(d, t):
        time_state = d.get('time', {}).get('state', '中期')
        evidence = d.get('time', {}).get('evidence', [])
        ev_text = evidence[0] if evidence else '无明确证据'
        return f"信号处于{time_state}阶段，{ev_text}"
    
    def _structure_plain(d, t):
        struct = d.get('structure', {}).get('state', '盘整')
        pos = d.get('position', {}).get('state', '中位')
        return f"走势{struct}，价格处于{pos}"
    
    def _vp_plain(d, t):
        vp_state = d.get('vp', {}).get('state', '中性')
        evidence = d.get('vp', {}).get('evidence', [])
        ev_text = evidence[0] if evidence else ''
        return f"量价关系{vp_state}，{ev_text}" if ev_text else f"量价关系{vp_state}"
    
    def _chip_plain(d, t):
        chip_state = d.get('chip_fund', {}).get('state', '中性')
        return f"资金面{chip_state}"
    
    def _emotion_plain(d, t):
        emo = d.get('emotion', {}).get('state', '正常')
        event = d.get('event', {}).get('state', '中性')
        return f"市场情绪{emo}，事件影响{event}"
    
    def _risk_plain(d, t):
        risk = d.get('risk', {}).get('state', '中')
        val = d.get('valuation', {}).get('state', '合理')
        fin = d.get('finance', {}).get('state', '关注')
        return f"风险等级{risk}，估值{val}，财务{fin}"
    
    segments = {
        'signal': _seg('信号确认状态', 'signal', dims.get('time', {}).get('light', 'yellow'),
                       lambda d,t: f"信号生命周期：{d.get('time', {}).get('state', '中期')}",
                       _signal_plain),
        'structure': _seg('结构位置状态', 'structure', dims.get('structure', {}).get('light', 'yellow'),
                          lambda d,t: f"走势结构：{d.get('structure', {}).get('state', '盘整')}；价格位置：{d.get('position', {}).get('state', '中位')}",
                          _structure_plain),
        'volume_price': _seg('量价健康度', 'volume_price', dims.get('vp', {}).get('light', 'yellow'),
                             lambda d,t: f"量价健康度：{d.get('vp', {}).get('state', '中性')}",
                             _vp_plain),
        'fund_chip': _seg('资金与筹码状态', 'fund_chip', dims.get('chip_fund', {}).get('light', 'yellow'),
                          lambda d,t: f"筹码资金：{d.get('chip_fund', {}).get('state', '中性')}",
                          _chip_plain),
        'emotion': _seg('情绪环境状态', 'emotion', dims.get('emotion', {}).get('light', 'yellow'),
                        lambda d,t: f"市场情绪：{d.get('emotion', {}).get('state', '正常')}；事件：{d.get('event', {}).get('state', '中性')}",
                        _emotion_plain),
        'risk': _seg('风险边界状态', 'risk', dims.get('risk', {}).get('light', 'yellow'),
                     lambda d,t: f"风险等级：{d.get('risk', {}).get('state', '中')}；估值：{d.get('valuation', {}).get('state', '合理')}；财务：{d.get('finance', {}).get('state', '关注')}",
                     _risk_plain),
        'summary': _seg('状态总结（仪表盘）', None, 
                        'green' if state in ('enter', 'light') else 'yellow',
                        lambda d,t: f"{st}（{state}）——维度共识 {snapshot_row.get('consensus_rate', 0):.0%}",
                        lambda d,t: f"整体处于{st}状态"),
    }
    
    return segments
```

### 2.3 修改：_status_bar() 5态扩展

**修改文件**：`backend/app/opportunity_atlas/status_engine.py`

**修改行号**：535-546

```python
def _status_bar(self, dims: dict, state: str, l0: dict = None) -> str:
    """364a Phase 1：status_bar 5态扩展"""
    green = sum(1 for d in dims.values() if d.get('light') == 'green')
    red = sum(1 for d in dims.values() if d.get('light') == 'red')
    l0 = l0 or {}
    
    # 优先级1：不可交易
    if state == 'avoid':
        return '不可交易'
    # 优先级2：风险区（硬否决或红灯≥6）
    if l0.get('hard_veto') or red >= 6:
        return '风险区'
    # 优先级3：持有观望
    if l0.get('hold_only'):
        return '持有观望'
    # 优先级4：强趋势
    if green >= 6:
        return '强趋势'
    # 优先级5：趋势确认
    if green >= 4:
        return '趋势确认'
    # 优先级6：趋势转弱
    if red >= 4:
        return '趋势转弱'
    # 默认：趋势不明
    return '趋势不明'
```

**注意**：调用`_status_bar()`的地方需同步传入l0参数。

### 2.4 新增：_generate_summary_text()

**修改文件**：`backend/app/opportunity_atlas/status_engine.py`

**新增位置**：`build_seven_dim_report()`函数内部或独立函数

```python
def _generate_summary_text(dims: dict, status_bar: str, consensus_rate: float) -> str:
    """364a Phase 1：从6维度关键信息生成一句话总结"""
    parts = []
    
    # 状态条
    parts.append(status_bar)
    
    # 各维度关键状态
    dim_summary = {
        'structure': ('结构', {'上升': '上升趋势', '下降': '下降趋势', '盘整': '盘整'}),
        'vp': ('量价', {'强健康': '量价健康', '健康': '量价良好', '背离': '量价背离', '中性': '量价中性'}),
        'chip_fund': ('资金', {'流入': '资金流入', '流出': '资金流出', '中性': '资金中性'}),
        'emotion': ('情绪', {'复苏': '情绪复苏', '退潮·高潮': '情绪退潮', '正常': '情绪正常'}),
    }
    
    for dim_key, (name, mapping) in dim_summary.items():
        state = dims.get(dim_key, {}).get('state', '')
        if state in mapping:
            parts.append(mapping[state])
    
    return '，'.join(parts)
```

### 2.5 修改：status_snapshot表结构

**修改文件**：`backend/app/data/enhanced_cache_manager.py`

**修改位置**：status_snapshot表定义（约L774-789）

**新增字段**：
```sql
ALTER TABLE status_snapshot ADD COLUMN summary_text TEXT;
ALTER TABLE status_snapshot ADD COLUMN one_liner_detail TEXT;
```

### 2.6 修改：_build_status_snapshot() 写入新字段

**修改文件**：`backend/data_daemon.py`

**修改位置**：`_build_status_snapshot()`函数（约L3768-3851）

**修改内容**：在写入status_snapshot时增加summary_text和one_liner_detail字段。

### 2.7 修改：_assemble() 输出增加新字段

**修改文件**：`backend/app/opportunity_atlas/status_engine.py`

**修改位置**：`_assemble()`函数（约L548-572）

**修改内容**：输出增加summary_text和one_liner_detail。

---

## 三、调用链变更

```
旧链路：
  status_engine.evaluate() → _assemble() → status_snapshot行
  strategy_analyze.py → 读status_snapshot → build_seven_dim_report(row) → API

新链路：
  status_engine.evaluate() → _assemble() → status_snapshot行（含summary_text+one_liner_detail）
  strategy_analyze.py → 读status_snapshot → build_seven_dim_report(row, tags) → API
```

**关键变更**：`build_seven_dim_report()`新增`tags`参数（从pre_feat_cache读取）。

---

## 四、测试用例

### 4.1 单元测试

| 测试项 | 输入 | 预期输出 |
|--------|------|---------|
| audit字段生成 | dims={risk:{state:'低'},valuation:{state:'合理'},finance:{state:'健康'}} | risk audit: 3/3 conditions satisfied |
| judgment字段生成 | dims={time:{state:'初期'}} | signal.judgment='信号初期' |
| plain动态生成 | dims={vp:{state:'健康',evidence:['VP-1']}} | volume_price.plain='量价关系健康，VP-1' |
| status_bar 5态 | state='avoid' | status_bar='不可交易' |
| status_bar 5态 | state='wait', l0={'hold_only':True} | status_bar='持有观望' |
| summary_text | dims={...}, status_bar='趋势确认' | summary_text='趋势确认，上升趋势，量价健康' |

### 4.2 集成测试

1. 运行全量pytest确认无回归
2. 调用`/api/v3/strategy-analyze`接口，验证返回的seven_dim_report包含audit/judgment/plain字段
3. 浏览器验证indicator-ide.html正确渲染audit条件列表

---

## 五、实施步骤

| 步骤 | 内容 | 工作量 |
|------|------|:------:|
| 1 | condition_auditor.py已创建 | ✅ 0h |
| 2 | 修改build_seven_dim_report()增加audit+judgment+plain | 3h |
| 3 | 修改_status_bar()为5态 | 0.5h |
| 4 | 新增_generate_summary_text() | 1h |
| 5 | 修改status_snapshot表结构（新增2字段） | 0.5h |
| 6 | 修改_build_status_snapshot()写入新字段 | 1h |
| 7 | 修改_assemble()输出增加新字段 | 0.5h |
| 8 | 修改strategy_analyze.py传递tags参数 | 0.5h |
| 9 | 单元测试+集成测试 | 1h |
| **合计** | | **8h** |

---

## 修订记录

| 版本 | 日期 | 修订内容 |
|------|------|---------|
| v1.0 | 2026-08-21 | 初版：详细修订内容+数据结构+调用链+测试用例 |
