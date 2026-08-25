---
title: Phase 9 - 集成测试与前端适配
type: 实施方案（子方案）
date: 2026-08-21
version: v1.0
parent: 364-七维现状描述系统实施方案（总纲）
depends: Phase 1-8
---

# 364i - Phase 9：集成测试与前端适配（6h）

> 目标：全链路验证七维现状描述系统，适配前端渲染，确保API→前端数据流完整。

---

## 一、strategy_analyze.py API输出变更

### 1.1 当前输出结构（strategy_analyze.py L954-976）

```python
response = {
    'code': 0,
    'data': {
        'ts_code': ts_code,
        'dimensions': dimensions,           # 五维展示格式（chanlun/volume_price/chip/emotion/factor）
        'operation_advice': response_advice, # 操作建议
        'seven_dim_report': _seven_dim_report, # 七维模板（当前简化版）
        'status_snapshot': _status_row,       # 成品仓快照
        'status_verdict': _status_verdict,    # 实时评估结论
        'nlg_status_text': ...,               # NLG渲染文本
        'deepseek_available': ...,            # DeepSeek可用性
        'deepseek_text': '',                  # DeepSeek文本（空）
    }
}
```

### 1.2 变更内容

**变更1：seven_dim_report 增加 audit/judgment/plain 字段**

364a Phase 1 已实现 `build_seven_dim_report()` 重构，需确保 API 传递 `tags` 参数：

```python
# 当前（L931-932）
from app.opportunity_atlas.status_engine import build_seven_dim_report
_seven_dim_report = build_seven_dim_report(_r.to_dict())

# 变更后（需补充 tags 参数）
from app.opportunity_atlas.status_engine import build_seven_dim_report
# 读取 pre_feat_cache 标签（供 audit 稽核器使用）
try:
    _tags = _dm.cache.get_tags(ts_code)
except Exception:
    _tags = None
_seven_dim_report = build_seven_dim_report(_r.to_dict(), tags=_tags)
```

**变更2：新增 summary_text 和 one_liner_detail 字段透出**

```python
# 在 _status_row 中增加字段
_status_row = {
    'opportunity_state': _r.get('opportunity_state'),
    'status_bar': _r.get('status_bar'),
    'consensus_rate': _r.get('consensus_rate'),
    'direction': _r.get('direction'),
    'conflict_evidence': _r.get('conflict_evidence'),
    'dim_states': _r.get('dim_states'),
    # 364a Phase 1 新增字段
    'summary_text': _r.get('summary_text'),
    'one_liner_detail': _r.get('one_liner_detail'),
}
```

**变更3：status_verdict 增加 dim_engine_results（Phase 8引擎输出）**

```python
# 在 _status_verdict 中增加维度引擎输出（Phase 8）
_status_verdict = {
    'opportunity_state': _verdict['opportunity_state'],
    'status_bar': _verdict['status_bar'],
    'consensus_rate': _verdict['consensus_rate'],
    'direction': _verdict['direction'],
    'conflict_evidence': _json3.loads(_verdict['conflict_evidence'] or '[]'),
    'dim_states': _json3.loads(_verdict['dim_states'] or '{}'),
    'advice_params': _json3.loads(_verdict['advice_params'] or '{}'),
    # 364h Phase 8 新增：各维度引擎完整输出
    'dim_engine_results': _verdict.get('dim_engine_results', {}),
}
```

### 1.3 完整变更文件清单

| # | 文件 | 变更位置 | 变更内容 |
|---|------|---------|---------|
| 1 | `strategy_analyze.py` L919-932 | 读取tags并传递给build_seven_dim_report | 增加tags参数 |
| 2 | `strategy_analyze.py` L922-930 | _status_row增加字段 | 增加summary_text + one_liner_detail |
| 3 | `strategy_analyze.py` L937-950 | _status_verdict增加字段 | 增加dim_engine_results |

---

## 二、indicator-ide.html 七维渲染适配

### 2.1 当前渲染结构

七维模板的前端渲染位于 `_ui-prototype/indicator-ide.html`，当前结构为：

```html
<!-- 当前七维渲染（简化版） -->
<div class="dimension-card" v-for="seg in seven_dim_report">
    <div class="dim-header">
        <span class="dim-light">{{ seg.light }}</span>
        <span class="dim-title">{{ seg.title }}</span>
    </div>
    <div class="dim-body">
        <div class="dim-text">{{ seg.text }}</div>
        <div class="dim-plain" v-if="seg.plain">{{ seg.plain }}</div>
    </div>
</div>
```

### 2.2 适配变更：增加 audit 列表 + plain 描述

**新增audit条件稽核列表渲染**：

```html
<!-- 适配后七维渲染 -->
<div class="dimension-card" v-for="(seg, key) in seven_dim_report">
    <div class="dim-header">
        <span class="dim-light">{{ seg.light }}</span>
        <span class="dim-title">{{ seg.title }}</span>
        <!-- 新增：judgment判定标签 -->
        <span class="dim-judgment" v-if="seg.judgment">{{ seg.judgment }}</span>
    </div>
    <div class="dim-body">
        <div class="dim-text">{{ seg.text }}</div>
        <!-- 新增：audit条件稽核列表 -->
        <div class="dim-audit" v-if="seg.audit && seg.audit.conditions && seg.audit.conditions.length">
            <div class="audit-summary">
                稽核: {{ seg.audit.satisfied_count }}/{{ seg.audit.total_count }} 通过
                （置信度 {{ (seg.audit.confidence * 100).toFixed(0) }}%）
            </div>
            <div class="audit-conditions">
                <div class="audit-condition"
                     v-for="cond in seg.audit.conditions"
                     :class="{ 'satisfied': cond.satisfied, 'unsatisfied': !cond.satisfied }">
                    <span class="cond-icon">{{ cond.satisfied ? '✅' : '❌' }}</span>
                    <span class="cond-name">{{ cond.name }}</span>
                    <span class="cond-detail">{{ cond.detail }}</span>
                </div>
            </div>
        </div>
        <!-- 新增：plain动态白话描述 -->
        <div class="dim-plain" v-if="seg.plain">
            <em>{{ seg.plain }}</em>
        </div>
    </div>
</div>
```

**CSS样式新增**：

```css
/* audit 条件稽核列表样式 */
.dim-audit {
    margin-top: 8px;
    padding: 6px 10px;
    background: #f8f9fa;
    border-radius: 6px;
    font-size: 13px;
}
.audit-summary {
    font-weight: 600;
    color: #495057;
    margin-bottom: 4px;
}
.audit-condition {
    display: flex;
    align-items: center;
    gap: 6px;
    padding: 3px 0;
    font-size: 12px;
}
.audit-condition.satisfied {
    color: #28a745;
}
.audit-condition.unsatisfied {
    color: #dc3545;
}
.cond-icon {
    width: 16px;
    text-align: center;
}
.cond-name {
    font-weight: 500;
    min-width: 80px;
}
.cond-detail {
    color: #6c757d;
}
/* judgment 标签样式 */
.dim-judgment {
    margin-left: auto;
    padding: 2px 8px;
    border-radius: 4px;
    font-size: 12px;
    background: #e9ecef;
    color: #495057;
}
/* plain 白话描述样式 */
.dim-plain {
    margin-top: 6px;
    padding: 4px 8px;
    background: #fff3cd;
    border-left: 3px solid #ffc107;
    border-radius: 0 4px 4px 0;
    font-size: 13px;
    color: #856404;
    font-style: italic;
}
```

### 2.3 数据绑定适配

```javascript
// indicator-ide.html 数据获取逻辑
// 当前：直接读取API返回的seven_dim_report
// 适配后：检查audit字段是否存在，不存在则降级显示

async function loadSevenDimReport(tsCode) {
    const response = await fetch('/api/v3/strategy/analyze', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ ts_code: tsCode })
    });
    const data = await response.json();
    
    if (data.code === 0 && data.data.seven_dim_report) {
        const report = data.data.seven_dim_report;
        
        // 检查audit字段（兼容旧版无audit的数据）
        for (const [key, seg] of Object.entries(report)) {
            if (!seg.audit) {
                // 降级：无audit时显示简化信息
                seg.audit = { conditions: [], satisfied_count: 0, total_count: 0, confidence: 0 };
            }
            if (!seg.judgment) {
                seg.judgment = '';
            }
            if (!seg.plain) {
                seg.plain = '';
            }
        }
        
        return report;
    }
    return null;
}
```

### 2.4 渲染优先级

| 优先级 | 数据源 | 说明 |
|:------:|--------|------|
| 1 | `seven_dim_report` (含audit/judgment/plain) | 364a Phase 1 新版 |
| 2 | `seven_dim_report` (无audit/judgment) | 降级：简化显示 |
| 3 | `nlg_status_text` | NLG渲染文本 |
| 4 | `dimensions` (五维格式) | 最旧版兼容 |

---

## 三、opportunity-treemap.html 从旧版切换到新版

### 3.1 当前弹窗渲染（旧版）

```javascript
// opportunity-treemap.html 弹窗渲染（旧版）
// 使用 opportunity_profile（七维红绿灯）
function showDiagnosisPopup(stock) {
    const profile = stock.opportunity_profile || {};
    // 旧版：直接显示各维度红绿灯 + tags_summary
    let html = '<div class="diagnosis-popup">';
    for (const [dim, info] of Object.entries(profile)) {
        if (info.light && info.status) {
            html += `<div class="dim-row">
                <span class="dim-light">${info.light === 'green' ? '✅' : info.light === 'red' ? '🚫' : '⚠️'}</span>
                <span class="dim-name">${dimNameMap[dim] || dim}</span>
                <span class="dim-status">${info.status}</span>
            </div>`;
        }
    }
    html += '</div>';
    return html;
}
```

### 3.2 新版弹窗渲染

```javascript
// opportunity-treemap.html 弹窗渲染（新版）
// 使用 seven_dim_report（含audit/judgment/plain）
function showDiagnosisPopup(stock) {
    const report = stock.seven_dim_report || stock.status_verdict?.seven_dim_report || {};
    const dimNameMap = {
        'signal': '① 信号确认',
        'structure': '② 结构位置',
        'volume_price': '③ 量价健康',
        'fund_chip': '④ 资金筹码',
        'emotion': '⑤ 情绪环境',
        'risk': '⑥ 风险边界',
        'summary': '⑦ 状态总结',
    };
    
    let html = '<div class="diagnosis-popup">';
    
    // 状态条
    const statusBar = stock.status_bar || '';
    const opportunityState = stock.opportunity_state || '';
    html += `<div class="status-bar">
        <span class="status-label">${statusBar}</span>
        <span class="status-state">${opportunityState}</span>
    </div>`;
    
    // 七维逐段渲染
    const dimOrder = ['signal', 'structure', 'volume_price', 'fund_chip', 'emotion', 'risk', 'summary'];
    for (const key of dimOrder) {
        const seg = report[key];
        if (!seg) continue;
        
        html += `<div class="dim-section">`;
        
        // 维度头（灯 + 标题 + judgment）
        html += `<div class="dim-header">
            <span class="dim-light">${seg.light || '⚠️'}</span>
            <span class="dim-title">${dimNameMap[key] || seg.title || key}</span>`;
        if (seg.judgment) {
            html += `<span class="dim-judgment">${seg.judgment}</span>`;
        }
        html += `</div>`;
        
        // 维度内容
        html += `<div class="dim-content">`;
        
        // text字段（传统描述）
        if (seg.text) {
            html += `<div class="dim-text">${seg.text}</div>`;
        }
        
        // audit条件稽核（新版核心字段）
        if (seg.audit && seg.audit.conditions && seg.audit.conditions.length > 0) {
            html += `<div class="dim-audit">
                <div class="audit-header">
                    条件稽核: ${seg.audit.satisfied_count}/${seg.audit.total_count} 通过
                </div>`;
            for (const cond of seg.audit.conditions) {
                html += `<div class="audit-row ${cond.satisfied ? 'pass' : 'fail'}">
                    <span>${cond.satisfied ? '✅' : '❌'}</span>
                    <span class="cond-name">${cond.name}</span>
                    <span class="cond-actual">${cond.actual}</span>
                    <span class="cond-threshold">(${cond.threshold})</span>
                </div>`;
            }
            html += `</div>`;
        }
        
        // plain白话描述
        if (seg.plain) {
            html += `<div class="dim-plain">💬 ${seg.plain}</div>`;
        }
        
        html += `</div></div>`;
    }
    
    // 冲突证据
    const conflict = stock.conflict_evidence || [];
    if (conflict.length > 0) {
        html += `<div class="conflict-section">
            <div class="conflict-header">⚠️ 冲突信号</div>`;
        for (const c of conflict) {
            html += `<div class="conflict-item">• ${c}</div>`;
        }
        html += `</div>`;
    }
    
    html += '</div>';
    return html;
}
```

### 3.3 数据源切换

| 旧版数据源 | 新版数据源 | 切换方式 |
|-----------|-----------|---------|
| `stock.opportunity_profile` | `stock.seven_dim_report` | 优先读新版，降级读旧版 |
| `stock.tags_summary` | `stock.summary_text` | 新增summary_text字段 |
| `stock.dim_states` | `stock.dim_engine_results` | Phase 8引擎输出 |

### 3.4 兼容性处理

```javascript
// 弹窗渲染兼容性：新旧版无缝切换
function getStockReport(stock) {
    // 优先级1：新版 seven_dim_report（含audit/judgment/plain）
    if (stock.seven_dim_report && Object.keys(stock.seven_dim_report).length > 0) {
        return stock.seven_dim_report;
    }
    // 优先级2：status_verdict 中的 seven_dim_report
    if (stock.status_verdict?.seven_dim_report) {
        return stock.status_verdict.seven_dim_report;
    }
    // 优先级3：从 dim_states 构建简化报告（旧版兼容）
    if (stock.dim_states) {
        return buildSimpleReportFromDimStates(stock.dim_states);
    }
    return null;
}
```

---

## 四、全链路集成测试方案

### 4.1 测试链路

```
数据层 → PRE管道 → status_engine → status_snapshot → API → 前端
  │         │           │               │            │       │
  │    pre_feat_cache   │          status_snapshot   │    渲染
  │    strategy_signal  │          seven_dim_report  │    audit列表
  │    detail           │          summary_text      │    plain描述
  │                     │          one_liner_detail   │    judgment标签
  │                     │                            │
  └─ 数据质量检查 ──────┴─ 维度引擎评估 ──────────────┴─ API输出验证
```

### 4.2 测试用例清单

#### 4.2.1 数据层测试

| # | 测试项 | 输入 | 预期输出 | 验证方式 |
|---|--------|------|---------|---------|
| D1 | pre_feat_cache数据完整性 | 全市场股票 | 每股有11组特征 | SQL查询 |
| D2 | strategy_signal_detail完整性 | 全市场股票 | 每股有≥1个引擎信号 | SQL查询 |
| D3 | status_snapshot生成 | 日终批量 | 每股有dim_states | SQL查询 |
| D4 | summary_text字段 | 日终批量 | 非空字符串 | SQL查询 |
| D5 | one_liner_detail字段 | 日终批量 | 非空字符串 | SQL查询 |

#### 4.2.2 维度引擎测试

| # | 测试项 | 输入 | 预期输出 | 验证方式 |
|---|--------|------|---------|---------|
| E1 | dim1信号引擎 | 有活跃信号的股票 | signal.audit有≥2个conditions | 单元测试 |
| E2 | dim2结构引擎 | 有缠论信号的股票 | structure连续值非0 | 单元测试 |
| E3 | dim3量价引擎 | 有量价信号的股票 | vp.audit.量比条件通过 | 单元测试 |
| E4 | dim4资金引擎 | 有筹码信号的股票 | chip_fund连续值非0 | 单元测试 |
| E5 | dim5情绪引擎 | 有BOCIASI信号的股票 | emotion.audit通过 | 单元测试 |
| E6 | dim6风险引擎 | 全市场 | risk.audit有3个conditions | 单元测试 |
| E7 | shared_vol_ratio | 全市场 | vol_ratio>0 | 单元测试 |
| E8 | shared_support_resistance | 全市场 | support<resistance | 单元测试 |

#### 4.2.3 API输出测试

| # | 测试项 | 输入 | 预期输出 | 验证方式 |
|---|--------|------|---------|---------|
| A1 | seven_dim_report字段 | POST /api/v3/strategy/analyze | 7个segment | API调用 |
| A2 | audit字段存在 | 同上 | 每segment有audit | API调用 |
| A3 | judgment字段存在 | 同上 | 每segment有judgment | API调用 |
| A4 | plain字段存在 | 同上 | 每segment有plain（非硬编码） | API调用 |
| A5 | summary_text | 同上 | status_snapshot.summary_text非空 | API调用 |
| A6 | status_bar 5态 | state='avoid' | '不可交易' | API调用 |
| A7 | dim_engine_results | 同上 | Phase 8引擎输出 | API调用 |

#### 4.2.4 前端渲染测试

| # | 测试项 | 输入 | 预期输出 | 验证方式 |
|---|--------|------|---------|---------|
| F1 | indicator-ide七维渲染 | 打开个股页 | 7个维度卡片显示 | 浏览器 |
| F2 | audit条件列表 | 有audit的segment | 条件列表正确显示（✅/❌） | 浏览器 |
| F3 | plain白话描述 | 有plain的segment | 白话描述正确显示 | 浏览器 |
| F4 | judgment标签 | 有judgment的segment | 判定标签显示 | 浏览器 |
| F5 | treemap弹窗 | 点击方块 | 新版七维弹窗 | 浏览器 |
| F6 | treemap旧版兼容 | 无seven_dim_report | 降级到旧版显示 | 浏览器 |
| F7 | 深色模式 | 切换主题 | audit/plain正确配色 | 浏览器 |

### 4.3 测试执行脚本

```python
"""
test_integration_364.py — 364号全链路集成测试
"""
import pytest
import json


class Test364Integration:
    """364号方案全链路集成测试"""
    
    def setup_method(self):
        from app import create_app
        self.app = create_app()
        self.client = self.app.test_client()
    
    def test_api_seven_dim_report_structure(self):
        """A1: API返回完整的七维报告结构"""
        resp = self.client.post('/api/v3/strategy/analyze',
                                json={'ts_code': '000001.SZ'})
        data = resp.get_json()
        assert data['code'] == 0
        report = data['data'].get('seven_dim_report')
        if report:
            expected_keys = {'signal', 'structure', 'volume_price', 'fund_chip', 'emotion', 'risk', 'summary'}
            assert set(report.keys()) == expected_keys
    
    def test_api_audit_fields(self):
        """A2: 每个segment包含audit字段"""
        resp = self.client.post('/api/v3/strategy/analyze',
                                json={'ts_code': '000001.SZ'})
        data = resp.get_json()
        report = data['data'].get('seven_dim_report')
        if report:
            for key, seg in report.items():
                assert 'audit' in seg, f"{key} 缺少 audit 字段"
                if seg['audit']:
                    assert 'conditions' in seg['audit']
                    assert 'satisfied_count' in seg['audit']
    
    def test_api_judgment_fields(self):
        """A3: 每个segment包含judgment字段"""
        resp = self.client.post('/api/v3/strategy/analyze',
                                json={'ts_code': '000001.SZ'})
        data = resp.get_json()
        report = data['data'].get('seven_dim_report')
        if report:
            for key, seg in report.items():
                assert 'judgment' in seg, f"{key} 缺少 judgment 字段"
    
    def test_api_plain_not_hardcoded(self):
        """A4: plain字段非硬编码"""
        resp = self.client.post('/api/v3/strategy/analyze',
                                json={'ts_code': '000001.SZ'})
        data = resp.get_json()
        report = data['data'].get('seven_dim_report')
        if report:
            for key, seg in report.items():
                if key == 'summary':
                    continue  # summary的plain是模板化
                plain = seg.get('plain', '')
                # plain不应是旧版硬编码文本
                assert plain != '最近信号的介入贵贱', f"{key} plain仍为硬编码"
                assert plain != '价格站在哪里、趋势方向', f"{key} plain仍为硬编码"
    
    def test_status_bar_five_states(self):
        """A6: status_bar 5态输出"""
        from app.opportunity_atlas.status_engine import StatusEngine
        engine = StatusEngine()
        # 测试 avoid → 不可交易
        dims = {}
        state = 'avoid'
        bar = engine._status_bar(dims, state)
        assert bar == '不可交易'
    
    def test_shared_vol_ratio(self):
        """E7: shared_vol_ratio计算正确"""
        from app.opportunity_atlas.dimensions.shared_vol_ratio import get_volume_ratio_service
        svc = get_volume_ratio_service()
        result = svc.compute('000001.SZ')
        assert result['vol_ratio'] > 0
        assert result['volume_status'] in ('极端放量', '明显放量', '温和放量', '量能正常', '量能萎缩', '极度萎缩')
    
    def test_shared_sr_service(self):
        """E8: shared_support_resistance返回有效数据"""
        from app.opportunity_atlas.dimensions.shared_support_resistance import get_support_resistance_service
        svc = get_support_resistance_service()
        sr = svc.get_support_resistance('000001.SZ', tags={}, signals={})
        assert sr['source'] != 'none'
```

---

## 五、性能测试要求

### 5.1 API响应时间

| 操作 | 当前耗时 | 目标耗时 | 说明 |
|------|:--------:|:--------:|------|
| `/api/v3/strategy/analyze` | 50-200ms | ≤200ms | 含七维报告组装 |
| `build_seven_dim_report()` | <5ms | ≤5ms | 纯模板组装 |
| `audit_dimension()` × 7 | <10ms | ≤10ms | 7个维度稽核 |
| `StatusEngine.evaluate()` | 100-500ms | ≤500ms | 含6维度引擎 |
| `shared_vol_ratio.compute()` | <10ms | ≤10ms | 量比计算 |
| `shared_sr.get_support_resistance()` | <10ms | ≤10ms | 支撑阻力 |

### 5.2 内存使用

| 资源 | 当前 | 目标 | 说明 |
|------|:----:|:----:|------|
| 6维度引擎实例 | — | ≤6个 | 全局单例 |
| 共享服务实例 | — | ≤2个 | sr_service + vol_service |
| 单股evaluate()内存增量 | — | ≤1MB | 不累积 |

### 5.3 并发测试

```bash
# 并发测试：100个并发请求
ab -n 100 -c 10 -p request.json -T 'application/json' \
   http://localhost:5000/api/v3/strategy/analyze

# 预期结果：
# - 平均响应时间 ≤ 200ms
# - 95分位 ≤ 500ms
# - 无 5xx 错误
```

### 5.4 全市场评估耗时

```python
# 全市场 status_snapshot 生成（日终批量）
# 当前：~5000只 × 200ms/只 ≈ 1000s（~17min）
# Phase 8优化后：维度引擎预计算 → evaluate()只做组装 ≈ 50ms/只 → 250s（~4min）
# 目标：≤5min（含日终同步）
```

---

## 六、实施步骤

| 步骤 | 内容 | 工作量 |
|------|------|:------:|
| 1 | strategy_analyze.py API输出变更 | 1h |
| 2 | indicator-ide.html 七维渲染适配（audit列表+plain描述） | 2h |
| 3 | opportunity-treemap.html 旧版→新版切换 | 1.5h |
| 4 | 全链路集成测试编写 | 1h |
| 5 | 性能测试 + 验证 | 0.5h |
| **合计** | | **6h** |

---

## 七、验收检查清单

| # | 验收项 | 标准 | 验证方法 | 状态 |
|---|--------|------|---------|:----:|
| 1 | API返回七维数据 | 7个segment均有title/light/audit/judgment/plain | API调用 | ☐ |
| 2 | audit条件稽核 | 每个segment有conditions[] | API调用 | ☐ |
| 3 | judgment独立判定 | 每个segment有judgment | API调用 | ☐ |
| 4 | plain动态白话 | 非硬编码，基于实际数据生成 | API调用 | ☐ |
| 5 | summary_text | status_snapshot中有值 | SQL查询 | ☐ |
| 6 | one_liner_detail | status_snapshot中有值 | SQL查询 | ☐ |
| 7 | indicator-ide渲染 | 七维卡片正确显示audit列表 | 浏览器 | ☐ |
| 8 | treemap弹窗 | 新版七维弹窗正确显示 | 浏览器 | ☐ |
| 9 | 旧版兼容 | 无新版数据时降级到旧版 | 浏览器 | ☐ |
| 10 | API响应时间 | ≤200ms | ab压测 | ☐ |
| 11 | 全量pytest | 325+ passed | pytest | ☐ |

---

## 修订记录

| 版本 | 日期 | 修订内容 |
|------|------|---------|
| v1.0 | 2026-08-21 | 初版：API变更+前端适配+集成测试+性能测试 |
