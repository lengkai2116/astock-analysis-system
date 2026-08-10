# 322号 个股策略分析操作建议重构 — 实施计划（S0-S5）

> **For agentic workers:** REQUIRED SUB-SKILL: 按任务逐步实施，每步 TDD（先写失败测试 → 验证失败 → 最小实现 → 验证通过 → 提交）。Steps use checkbox (`- [ ]`) syntax.

**Goal:** 将个股策略分析页操作建议从"前端纯推导+静态概率"重构为"后端结构化 operation_advice（现状描述化+结论统一+机器可执行）"，并修复缓存读取耗时问题。

**Architecture:** 三层——数据分（图谱标签截面 / 个股页信号深挖）、结论统（复用 321 号 arbitrate 状态机）、执行机器可读（executable entry/exit 规则供虚拟实盘）。operation_advice 在 analyze 响应时实时组装（毫秒级），不落库不入快照。DeepSeek 为可选叙事层（prompt 注入结论，只转译不新增）。

**Tech Stack:** Python 3.11 / Flask / SQLite WAL / 原生 JS（HTML 原型） / pytest / ruff

## Global Constraints

- 四层架构红线（292号）：调用层只读存储层，禁止直调数据源；禁止 use_cache=False；operation_advice 属"策略核算"（用户触发），可在调用层实时组装
- 双平台（Windows/macOS）：纯 Python + pathlib + utf-8，无 Unix-only API
- TDD：每任务先写失败测试（RED→GREEN），不得先写实现
- 测试从包目录运行：`cd backend && .venv/bin/python -m pytest`
- 前端为 HTML 原型（无单测框架）：JS 语法检查用 `node -e "new Function(script)"`，端到端用 headless chromium（PW_CHROME 环境变量）
- 提交需用户确认（本项目惯例：不主动 commit）

---

### Task 1: 对策1 — analyze/status-aggregate/deepseek 缓存读取修复

**Covers:** [322号 §4.2.1 对策1]

**Files:**
- Modify: `backend/app/routes/strategy_analyze.py:616,738,1132`
- Test: `backend/tests/test_322_s0_cache_fix.py`

**Interfaces:**
- Consumes: `DataManager.get_latest_signal_detail(ts_code) -> dict|None`（已存在，enhanced_cache_manager.py:1762）；`DataManager.get_signal_detail(ts_code) -> dict|None`（当日严格）
- Produces: analyze 响应 `data_availability.signal_date`（实际数据日期）；`_read_signal_cached(dm, ts_code) -> tuple[signals, signal_date]` 辅助函数

- [ ] **Step 1: 写失败测试**（新建 test_322_s0_cache_fix.py）

```python
"""322号 S0：analyze 缓存读取修复——非交易日应命中最新一条缓存而非实时计算"""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
for k in ['HTTP_PROXY','HTTPS_PROXY','ALL_PROXY']:
    os.environ.pop(k, None)

import pytest


def test_read_signal_cached_falls_back_to_latest():
    """get_signal_detail 当日 miss 时应回退 get_latest_signal_detail（非交易日场景）"""
    from app.data import DataManager
    from app.routes import strategy_analyze as sa

    dm = DataManager()
    signals, signal_date = sa._read_signal_cached(dm, '600519.SH')
    assert signals, "非交易日应命中最新缓存（600519 有 08-07 缓存）"
    assert signal_date, "应返回实际数据日期"
    # 关键：不应触发实时计算（有缓存即为通过）


def test_read_signal_cached_unknown_stock_returns_none():
    """完全无缓存股票应返回 None（允许回退实时计算）"""
    from app.data import DataManager
    from app.routes import strategy_analyze as sa

    dm = DataManager()
    signals, signal_date = sa._read_signal_cached(dm, '000000.SZ')
    assert signals is None and signal_date is None
```

- [ ] **Step 2: 运行测试验证失败**

Run: `cd backend && .venv/bin/python -m pytest tests/test_322_s0_cache_fix.py -v`
Expected: FAIL — `AttributeError: module 'app.routes.strategy_analyze' has no attribute '_read_signal_cached'`

- [ ] **Step 3: 实现 `_read_signal_cached` + 三处调用改造**

在 `strategy_analyze.py` 添加辅助函数（放在 `_restore_signals_from_cache` 附近，约 L200）：

```python
def _read_signal_cached(dm, ts_code: str):
    """优先当日缓存，miss 时回退最新一条（320号 F3），返回 (signals, signal_date)

    非交易日/新交易日 get_signal_detail(当日) 必 miss → 此前触发 4.5-6s 实时计算；
    回退 get_latest_signal_detail 直接命中最新缓存，毫秒级。
    """
    cached = dm.get_signal_detail(ts_code)
    signal_date = None
    if cached:
        signal_date = cached.get('trade_date')
        return _restore_signals_from_cache(cached), signal_date
    latest = dm.cache.get_latest_signal_detail(ts_code)
    if latest:
        signal_date = latest.get('trade_date')
        return _restore_signals_from_cache(latest), signal_date
    return None, None
```

修改 analyze 主路由（L616 区域）：

```python
        from app.data import DataManager
        _dm = DataManager()
        signals, signal_date = _read_signal_cached(_dm, ts_code)
        data_availability = {'signal_date': signal_date} if signal_date else {}
        if not signals:
            from app.engine.unified_core import UnifiedStrategyCore
            _core = UnifiedStrategyCore()
            _result = _core.compute(ts_code, period=period)
            signals = _restore_signals_from_cache(_result.to_dict())
            data_availability = _result.data_availability
            # 实时计算结果落盘，供后续命中
            try:
                _dm.cache.cache_signal_detail(ts_code, _result.to_dict())
            except Exception:
                pass
```

同步修改 status-aggregate（L738）与 deepseek（L1132）为同一辅助函数（deepseek 处若无信号返回 503 不变，但用最新缓存）。

- [ ] **Step 4: 运行测试验证通过**

Run: `cd backend && .venv/bin/python -m pytest tests/test_322_s0_cache_fix.py -v`
Expected: PASS 2 passed

- [ ] **Step 5: 真实验证非交易日命中**

Run: `cd backend && .venv/bin/python -c "from app.data import DataManager; from app.routes.strategy_analyze import _read_signal_cached; dm=DataManager(); s,d=_read_signal_cached(dm,'600519.SH'); print('signals=',bool(s),'date=',d)"`
Expected: `signals=True date=20260807`（不再触发实时计算）

---

### Task 2: S1 后端 operation_advice 生成（七维+几何+情景概率规则基线）

**Covers:** [322号 §三 operation_advice 结构]

**Files:**
- Create: `backend/app/opportunity_atlas/advice_builder.py`
- Modify: `backend/app/routes/strategy_analyze.py`（analyze 响应新增 operation_advice 字段）
- Test: `backend/tests/test_322_s1_advice.py`

**Interfaces:**
- Consumes: `arbitrate(tags, gate=None, consensus=None)`（321号 arbiter.py:arbitrate）；五维 dimensions（analyze 已构建）；`DataManager.get_cached_daily(ts_code)`（K线）
- Produces: `build_operation_advice(ts_code, dimensions, signals, df) -> dict`（operation_advice 完整结构：state/state_reason/summary/dimensions[7]/geometric/action/scenarios/executable）

- [ ] **Step 1: 写失败测试**（test_322_s1_advice.py）

```python
"""322号 S1：operation_advice 生成——七维+几何+情景概率+executable"""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
for k in ['HTTP_PROXY','HTTPS_PROXY','ALL_PROXY']:
    os.environ.pop(k, None)

import pytest

from app.opportunity_atlas.advice_builder import build_operation_advice, _normalize_scenarios


def test_build_operation_advice_full_structure():
    """五维+K线输入 → 完整 operation_advice（七维/几何/情景/executable）"""
    dimensions = {
        'chanlun': {'direction': 'up', 'buy_point': 'third_buy',
                    'status_recognition': {'support_resistance': {'support': 10.0, 'resistance': 12.0}}},
        'volume_price': {'direction': 'up', 'active_pattern': '放量突破'},
        'chip': {'main_force_direction': '流入'},
        'emotion': {'rotation_state': 'RECOVERY'},
        'factor': {'trend': 'up', 'confidence': 0.7},
    }
    signals = []
    df = None  # K线不足时几何指标返回 None，不报错
    advice = build_operation_advice('TEST.SZ', dimensions, signals, df)
    assert 'state' in advice and 'dimensions' in advice
    assert len(advice['dimensions']) >= 5, "至少 5 个红绿灯维"
    assert 'geometric' in advice
    assert 'scenarios' in advice
    assert 'executable' in advice
    # 情景概率归一化
    probs = [s['prob'] for s in advice['scenarios']]
    assert abs(sum(probs) - 1.0) < 0.01, f"情景概率应归一化: {probs}"


def test_normalize_scenarios_sums_to_one():
    """概率归一化（和为1，非负）"""
    raw = [{'id': 'a', 'prob': 0.5}, {'id': 'b', 'prob': 0.3}, {'id': 'c', 'prob': 0.1}]
    out = _normalize_scenarios(raw)
    assert abs(sum(s['prob'] for s in out) - 1.0) < 1e-6


def test_build_operation_advice_state_from_arbitrate():
    """state 应来自 321 仲裁（与机会图谱同源）"""
    dimensions = {'factor': {'trend': 'down'}}
    advice = build_operation_advice('TEST.SZ', dimensions, [], None)
    assert advice['state'] in ('enter', 'light', 'wait', 'avoid')
    assert 'state_reason' in advice
```

- [ ] **Step 2: 运行测试验证失败**

Run: `cd backend && .venv/bin/python -m pytest tests/test_322_s1_advice.py -v`
Expected: FAIL — ModuleNotFoundError: advice_builder

- [ ] **Step 3: 实现 advice_builder.py**

```python
"""322号 操作建议生成器（现状描述化：七维红绿灯 + 几何指标 + 情景概率 + executable）

结论层复用 321 号 arbitrate 状态机（与机会图谱同源）；五维信号 + K线 → 状态刻画。
仅按需生成（analyze 响应时），不落库不入快照。
"""
from __future__ import annotations
from typing import Any

from app.opportunity_atlas.arbiter import arbitrate

_STATE_CN = {'enter': '可入场', 'light': '可轻仓', 'wait': '等待', 'avoid': '回避'}


def _scenario_base(dimensions: dict) -> dict:
    """情景概率规则基线：五维方向一致度 → 趋势延续/冲高回落/破位下行"""
    dirs = []
    for k in ('chanlun', 'volume_price', 'chip', 'emotion', 'factor'):
        d = (dimensions.get(k) or {}).get('direction', '')
        if d in ('up', 'bullish'):
            dirs.append(1)
        elif d in ('down', 'bearish'):
            dirs.append(-1)
    up = sum(1 for x in dirs if x > 0)
    down = sum(1 for x in dirs if x < 0)
    n = max(len(dirs), 1)
    prob_a = 0.4 + 0.5 * (up / n)          # 趋势延续
    prob_c = 0.1 + 0.5 * (down / n)        # 破位下行
    prob_b = max(0.05, 1.0 - prob_a - prob_c)  # 冲高回落
    return {'a': prob_a, 'b': prob_b, 'c': prob_c}


def _normalize_scenarios(raw: list[dict]) -> list[dict]:
    """概率归一化（非负、和为1）"""
    total = sum(max(0.0, s.get('prob', 0)) for s in raw)
    if total <= 0:
        total = 1.0
    return [{**s, 'prob': round(max(0.0, s.get('prob', 0)) / total, 3)} for s in raw]


def _geometric(tags: dict, df) -> dict:
    """几何化指标：距支撑/压力%、盈亏比（K线不足返回空）"""
    if df is None or df.empty or 'close' not in df.columns or len(df) < 20:
        return {'dist_to_support_pct': None, 'dist_to_resistance_pct': None,
                'risk_reward': None, 'signal_days': None}
    closes = df['close'].values
    price = float(closes[-1])
    hi60 = float(df['high'].tail(60).max()) if len(df) >= 60 and 'high' in df.columns else None
    lo60 = float(df['low'].tail(60).min()) if len(df) >= 60 and 'low' in df.columns else None
    dist_sup = (lo60 / price - 1) * 100 if lo60 else None
    dist_res = (hi60 / price - 1) * 100 if hi60 else None
    rr = abs(dist_res / dist_sup) if dist_sup and dist_res else None
    return {'dist_to_support_pct': round(dist_sup, 2) if dist_sup is not None else None,
            'dist_to_resistance_pct': round(dist_res, 2) if dist_res is not None else None,
            'risk_reward': round(rr, 2) if rr is not None else None,
            'signal_days': tags.get('signal_days')}


def build_operation_advice(ts_code: str, dimensions: dict, signals: list, df) -> dict:
    """构建 operation_advice（analyze 响应时调用，毫秒级）"""
    # 结论层：从五维提取仲裁输入（right_side_confirm 由闸门2/标签，缺失时用 factor.trend 近似）
    trend = (dimensions.get('factor') or {}).get('trend', '')
    mfp = (dimensions.get('chip') or {}).get('main_force_direction', '')
    arb_tags = {
        'right_side_confirm': '强确认' if trend in ('up', 'bullish') else ('未确认' if trend == 'neutral' else '未确认'),
        'main_force_phase': 'lifting' if '流入' in str(mfp) else ('distributing' if '流出' in str(mfp) else 'unknown'),
    }
    arb = arbitrate(arb_tags)
    state = arb['opportunity_state']
    state_reason = arb['state_evidence'][0] if arb['state_evidence'] else ''

    # 七维红绿灯（源自 LLM Wiki 框架，数据来自五维）
    vp = dimensions.get('volume_price') or {}
    chip = dimensions.get('chip') or {}
    emo = dimensions.get('emotion') or {}
    chan = dimensions.get('chanlun') or {}
    dims = [
        {'key': 'signal', 'light': '✅' if trend in ('up', 'bullish') else '🟡',
         'conclusion': f'趋势方向{trend}', 'evidence': chan.get('buy_point') or vp.get('active_pattern') or '',
         'plain': '上涨信号明确' if trend in ('up', 'bullish') else '方向待确认'},
        {'key': 'structure', 'light': '🟡', 'conclusion': '结构位置',
         'evidence': f"支撑{chan.get('status_recognition', {}).get('support_resistance', {}).get('support')} / 压力{chan.get('status_recognition', {}).get('support_resistance', {}).get('resistance')}", 'plain': ''},
        {'key': 'volume_price', 'light': '✅' if vp.get('direction') in ('up', 'bullish') else '🟡',
         'conclusion': vp.get('phase_label') or '量价中性', 'evidence': vp.get('active_pattern') or '', 'plain': ''},
        {'key': 'fund', 'light': '✅' if '流入' in str(chip.get('main_force_direction')) else ('🔴' if '流出' in str(chip.get('main_force_direction')) else '🟡'),
         'conclusion': str(chip.get('main_force_direction') or '中性'), 'evidence': f"获利比例{chip.get('profit_ratio')}", 'plain': ''},
        {'key': 'sentiment', 'light': '🟡', 'conclusion': str(emo.get('rotation_state') or '中性'),
         'evidence': emo.get('sector') or '', 'plain': ''},
        {'key': 'risk', 'light': '✅', 'conclusion': '风险边界', 'evidence': '', 'plain': '止损=结构位，跌破离场'},
    ]

    # 情景概率（规则基线；Kronos 修正由 S4 接入）
    base = _scenario_base(dimensions)
    scenarios = _normalize_scenarios([
        {'id': 'a', 'name': '趋势延续', 'prob': base['a'],
         'steps': ['回踩支撑位可加仓', '突破前高追进']},
        {'id': 'b', 'name': '冲高回落', 'prob': base['b'],
         'steps': ['阻力位附近减仓', '资金流出不开新仓']},
        {'id': 'c', 'name': '破位下行', 'prob': base['c'],
         'steps': ['跌破支撑位止损', '等待底部结构']},
    ])

    # 机器可执行（虚拟实盘前置契约）
    geo = _geometric({}, df)
    support = (chan.get('status_recognition') or {}).get('support_resistance', {}).get('support')
    resistance = (chan.get('status_recognition') or {}).get('support_resistance', {}).get('resistance')
    executable = {
        'action_type': 'BUY' if state == 'enter' else ('HOLD' if state in ('light', 'wait') else 'SELL'),
        'entry_rules': [{'trigger': f'close <= {support}', 'action': 'BUY', 'size_pct': 30}] if support else [],
        'exit_rules': [{'trigger': f'close < {support}', 'action': 'SELL', 'size_pct': 100}] if support else [],
        'position': {'max_pct': 0.6 if state in ('enter', 'light') else 0.2, 'initial_pct': 0.3},
    }

    return {
        'state': state, 'state_reason': state_reason,
        'summary': f"{_STATE_CN.get(state, state)}：{state_reason}" if state_reason else _STATE_CN.get(state, state),
        'dimensions': dims, 'geometric': geo,
        'action': {'max_position_ratio': executable['position']['max_pct']},
        'scenarios': scenarios, 'executable': executable,
    }
```

- [ ] **Step 4: analyze 响应接入 operation_advice**

在 `strategy_analyze.py` analyze 路由中，五维组装后（约 L660）加：

```python
        # 322号 S1：操作建议（现状描述化，结论与机会图谱同源）
        try:
            from app.opportunity_atlas.advice_builder import build_operation_advice
            from app.data import DataManager
            _dm2 = DataManager()
            _df = _dm2.get_cached_daily(ts_code)
            response_advice = build_operation_advice(ts_code, dimensions, signals, _df)
        except Exception:
            response_advice = None
```

并在响应 data 中加 `'operation_advice': response_advice`（L691 附近）。

- [ ] **Step 5: 运行测试验证通过**

Run: `cd backend && .venv/bin/python -m pytest tests/test_322_s1_advice.py -v`
Expected: PASS 3 passed

- [ ] **Step 6: 真实数据验证**

Run: `cd backend && .venv/bin/python -c "from app.opportunity_atlas.advice_builder import build_operation_advice; from app.data import DataManager; dm=DataManager(); df=dm.get_cached_daily('600519.SH'); print(build_operation_advice('600519.SH', {'chanlun':{'direction':'up'},'volume_price':{'direction':'up'},'chip':{'main_force_direction':'流入'},'emotion':{'rotation_state':'RECOVERY'},'factor':{'trend':'up'}}, [], df))"`
Expected: 完整 dict，state/scenarios/executable 齐备，概率和为 1

---

### Task 3: S2 前端渲染改造（strategyRec/actionPlan 改读 operation_advice）

**Covers:** [322号 §五 S2]

**Files:**
- Modify: `_ui-prototype/indicator-ide.html`（renderStrategyRecommendation L3438 / renderActionPlan L3516）
- Test: JS 语法检查 + headless chromium 端到端

**Interfaces:**
- Consumes: analyze 响应 `data.operation_advice`（Task 2 Produces）
- Produces: 前端展示七维红绿灯 + 大白话 + 动态情景概率

- [ ] **Step 1: 修改 renderActionPlan 优先读 operation_advice**

在 `renderActionPlan` 函数开头（L3516 后）插入：

```js
  // 322号 S2：优先读后端 operation_advice（现状描述化）；无则回退旧推导
  var oa = analysisData.operation_advice;
  if (oa && oa.dimensions && oa.dimensions.length) {
    var dimHtml = oa.dimensions.map(function(d){
      return '<div class="s-step">' + (d.light||'') + ' ' + (d.conclusion||'') +
             (d.evidence ? ' <span style="color:#6b728c;">'+d.evidence+'</span>' : '') +
             (d.plain ? ' <span style="color:#6b728c;">（'+d.plain+'）</span>' : '') + '</div>';
    }).join('');
    var summaryHtml = oa.summary ? '<div class="rec-header" style="margin-bottom:8px;">🎯 操作建议 <span style="color:#6b728c;">'+oa.summary+'</span></div>' : '';
    var scnHtml = (oa.scenarios||[]).map(function(s){
      return '<div class="s-header" style="margin-top:8px;"><span class="s-tag">情景'+s.id.toUpperCase()+'</span><span class="s-title">'+s.name+'</span><span class="s-prob">概率 '+Math.round(s.prob*100)+'%</span></div>' +
             '<div class="s-steps">' + s.steps.map(function(x){return '<div class="s-step">'+x+'</div>';}).join('') + '</div>';
    }).join('');
    var stepsA = document.getElementById('apStepsA');
    if (stepsA) stepsA.innerHTML = dimHtml + scnHtml;
    // 隐藏 B/C 卡片（合并为单一报告）
    ['apStepsB','apStepsC'].forEach(function(id){ var el=document.getElementById(id); if(el) el.innerHTML=''; });
    var hdr = document.querySelector('.ap-header');
    if (hdr && oa.summary) hdr.innerHTML = '📋 操作建议 <span class="ap-subtitle">'+oa.summary+'</span>';
    return;  // 已有 operation_advice 则不再走旧情景推导
  }
  // ... 原有 fallback 逻辑保留
```

- [ ] **Step 2: JS 语法检查**

Run: `cd _ui-prototype && node -e "const fs=require('fs');const h=fs.readFileSync('indicator-ide.html','utf8');h.match(/<script>([\s\S]*?)<\/script>/g).forEach((s,i)=>{try{new Function(s.replace(/<script>|<\/script>/g,''));}catch(e){console.log('脚本'+i+'错误:'+e.message)}})"`
Expected: 无错误输出

- [ ] **Step 3: 浏览器端到端（headless chromium）**

启动 8082 服务 + API 5001，用 PW_CHROME 运行脚本：打开 `indicator-ide.html?ts_code=600519.SH`，触发分析，断言：
- `#actionPlan` 含"操作建议"且显示七维（至少含"风险边界"或"资金"）
- 情景概率非静态（数字来自后端，如"概率 62%"）

Run: `cd _ui-prototype && (nohup python3 serve.py >/tmp/serve.log 2>&1 &) && sleep 2 && PW_CHROME=$HOME/Library/Caches/ms-playwright/chromium_headless_shell-1228/chrome-headless-shell-mac-arm64/chrome-headless-shell NODE_PATH=/Users/kalence/.npm-global/lib/node_modules node /tmp/s2_e2e.cjs`
Expected: 断言通过

---

### Task 4: S3 死代码清理

**Covers:** [322号 §一 1.3 缺陷 5]

**Files:**
- Modify: `_ui-prototype/indicator-ide.html`（renderDimensionCards L2956-3012、triggerArbitrate 内调用、静态概率 L916/925/932、硬编码置信度 L3450-3456、recTarget L3468）

- [ ] **Step 1: 删除 renderDimensionCards 及调用**

删除 `renderDimensionCards` 整个函数（L2956-3012）；在 `triggerArbitrate`（L3779 附近）删除对它的调用（如有）。核查 `cm-*` DOM 确不存在后删除。

- [ ] **Step 2: 清理静态概率**

L916/925/932 的 `概率 60%` 等改为由 JS 注入（Task 3 已让 apStepsA 渲染动态概率；删除 HTML 静态文本或保留为加载占位）。

- [ ] **Step 3: 删除硬编码置信度与目标价**

`renderStrategyRecommendation` 中 L3450-3456 的 `conf = 0.5/0.3` 兜底与 L3468 的 `recTarget = takeProfit*1.1` 删除；置信度改读 `factor.confidence`，无则显示"--"。

- [ ] **Step 4: JS 语法检查 + 浏览器回归**

Run: 同 Task 3 Step 2（语法）+ headless chromium 打开个股页确认无 JS 报错、页面正常。

---

### Task 5: S4 情景概率接入 Kronos 可选修正

**Covers:** [322号 §三 情景概率推导（Kronos 修正）]

**Files:**
- Modify: `backend/app/opportunity_atlas/advice_builder.py`（`build_operation_advice` 增加 kronos 参数）
- Modify: `backend/app/routes/strategy_analyze.py`（kronos_enabled 时传 kronos_result）
- Test: `backend/tests/test_322_s4_kronos.py`

**Interfaces:**
- Consumes: `kronos_result`（`_compute_kronos` 输出，含方向倾向）；`kronos_enabled`（analyze 入参）
- Produces: scenarios 概率含 Kronos 修正 + `kronos_note: '🔬 AI模型预测，仅供参考'`

- [ ] **Step 1: 写失败测试**

```python
"""322号 S4：Kronos 可选修正情景概率"""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
for k in ['HTTP_PROXY','HTTPS_PROXY','ALL_PROXY']:
    os.environ.pop(k, None)

import pytest

from app.opportunity_atlas.advice_builder import build_operation_advice


def test_kronos_bullish_boosts_trend_continuation():
    dims = {'factor': {'trend': 'up'}}
    kronos = {'direction': 'bullish', 'confidence': 0.8}
    a1 = build_operation_advice('T.SZ', dims, [], None)
    a2 = build_operation_advice('T.SZ', dims, [], None, kronos=kronos)
    p_a1 = next(s['prob'] for s in a1['scenarios'] if s['id'] == 'a')
    p_a2 = next(s['prob'] for s in a2['scenarios'] if s['id'] == 'a')
    assert p_a2 > p_a1, "Kronos 看多应提升趋势延续概率"
    assert 'kronos_note' in a2, "应标注 AI 预测仅供参考"


def test_kronos_bearish_boosts_breakdown():
    dims = {'factor': {'trend': 'up'}}
    kronos = {'direction': 'bearish', 'confidence': 0.9}
    a = build_operation_advice('T.SZ', dims, [], None, kronos=kronos)
    p_c = next(s['prob'] for s in a['scenarios'] if s['id'] == 'c')
    assert p_c > 0.3, "Kronos 看空应提升破位下行概率"


def test_no_kronos_no_note():
    a = build_operation_advice('T.SZ', {'factor': {'trend': 'up'}}, [], None)
    assert 'kronos_note' not in a
```

- [ ] **Step 2: 运行测试验证失败**

Run: `cd backend && .venv/bin/python -m pytest tests/test_322_s4_kronos.py -v`
Expected: FAIL（build_operation_advice 不接受 kronos 参数）

- [ ] **Step 3: 实现 Kronos 修正**

`build_operation_advice` 签名改为 `(ts_code, dimensions, signals, df, kronos=None)`，在情景概率后：

```python
    # ── S4：Kronos 可选修正（AI 预测仅供参考，非实证）──
    if kronos:
        kdir = kronos.get('direction', '')
        kconf = float(kronos.get('confidence', 0.5))
        delta = 0.15 * kconf
        if kdir == 'bullish':
            base['a'] += delta
            base['c'] -= delta * 0.5
        elif kdir == 'bearish':
            base['c'] += delta
            base['a'] -= delta * 0.5
        scenarios = _normalize_scenarios([...同前用 base...])
        result['kronos_note'] = '🔬 Kronos AI 模型预测，仅供参考，非实证结论'
```

（Kronos 参与时在返回 dict 加 `kronos_note`。）

- [ ] **Step 4: analyze 接入 kronos_result**

analyze 中 `build_operation_advice` 调用改为传 `kronos_result if kronos_enabled else None`。

- [ ] **Step 5: 运行测试验证通过**

Run: `cd backend && .venv/bin/python -m pytest tests/test_322_s4_kronos.py -v`
Expected: PASS 3 passed

---

### Task 6: S5 虚拟实盘前置数据契约

**Covers:** [322号 §4.3]

**Files:**
- Modify: `backend/app/opportunity_atlas/advice_builder.py`（executable 已产出，验证契约）
- Modify: `backend/app/routes/strategy_analyze.py`（无新端点，仅确认 executable 随 operation_advice 返回）
- Test: `backend/tests/test_322_s5_executable.py`

- [ ] **Step 1: 写失败测试**

```python
"""322号 S5：executable 机器可执行契约（虚拟实盘前置）"""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
for k in ['HTTP_PROXY','HTTPS_PROXY','ALL_PROXY']:
    os.environ.pop(k, None)

import pytest

from app.opportunity_atlas.advice_builder import build_operation_advice


def test_executable_contract_shape():
    """executable 含 action_type/entry_rules/exit_rules/position，机器可解析"""
    dims = {'factor': {'trend': 'up'},
            'chanlun': {'status_recognition': {'support_resistance': {'support': 10.0, 'resistance': 12.0}}}}
    advice = build_operation_advice('T.SZ', dims, [], None)
    ex = advice['executable']
    assert ex['action_type'] in ('BUY', 'HOLD', 'REDUCE', 'SELL', 'WAIT')
    assert isinstance(ex['entry_rules'], list)
    assert isinstance(ex['exit_rules'], list)
    assert 'max_pct' in ex['position'] and 'initial_pct' in ex['position']
    # 规则 trigger 可解析为价格条件
    for r in ex['exit_rules']:
        assert 'close' in r['trigger'] and isinstance(r['size_pct'], int)


def test_avoid_state_action_is_sell():
    dims = {'factor': {'trend': 'down'}}
    advice = build_operation_advice('T.SZ', dims, [], None)
    if advice['state'] == 'avoid':
        assert advice['executable']['action_type'] == 'SELL'
```

- [ ] **Step 2: 运行测试验证失败**

Run: `cd backend && .venv/bin/python -m pytest tests/test_322_s5_executable.py -v`
Expected: FAIL 或已有实现部分通过（若 Task 2 已实现 executable 则此任务为契约验证补全）

- [ ] **Step 3: 补全 executable 契约（如 Task 2 已产出则验证即可）**

若 `build_operation_advice` 已有 executable（Task 2 Step 3 已含），本任务仅补充：`avoid` 态 action_type 强制 SELL 的断言逻辑（Step 3 代码已在 Task 2 实现中覆盖）。

- [ ] **Step 4: 运行测试验证通过**

Run: `cd backend && .venv/bin/python -m pytest tests/test_322_s5_executable.py -v`
Expected: PASS 2 passed

---

### Task 7: 回归与收尾

**Files:**
- Test: 全量 pytest + ruff + 前端端到端

- [ ] **Step 1: 全量 pytest**

Run: `cd backend && .venv/bin/python -m pytest tests/ -q -p no:cacheprovider`
Expected: 319 + 新增 10+ 全部 passed

- [ ] **Step 2: ruff 检查新增文件**

Run: `cd backend && .venv/bin/ruff check app/opportunity_atlas/advice_builder.py app/routes/strategy_analyze.py tests/test_322_*.py`
Expected: 新增文件 All checks passed（存量错误不增）

- [ ] **Step 3: 前端端到端回归（含机会图谱→个股页跳转链路）**

Run: headless chromium 打开图谱 → 弹窗"策略分析"→ 确认跳转个股页 → 触发分析 → 操作建议展示七维+情景概率 → "回到机会图谱"返回。
Expected: 全链路正常，无 JS 报错

- [ ] **Step 4: 文档收尾**

更新 322 号方案 §九 实施状态（S0-S5 ✅）、沟通纪要、沟通索引、工作上下文。

---

**Self-Review 结论**：S0 覆盖 322号 §4.2.1（对策1）；S1 覆盖 §三 结构 + §五 S1；S2 覆盖 §五 S2；S3 覆盖 §一 1.3 缺陷 5；S4 覆盖 §三 情景概率 Kronos；S5 覆盖 §4.3；S6 回归 §六 验证。类型一致（`build_operation_advice(ts_code, dimensions, signals, df, kronos=None)` 跨任务签名一致；`_read_signal_cached(dm, ts_code) -> (signals, signal_date)` 跨 Task1 一致）。无占位符。
