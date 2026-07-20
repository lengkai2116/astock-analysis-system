# 量价状态机精细化实施计划

> **Goal:** 对已上线的 VPStateMachine 进行精细化改进，包括极端信号改用历史极值、背离条件修正、连续确认切换、显式状态转换规则。

**Architecture:** 所有修改集中在 `volume_price_strategy.py` 的 VPStateMachine 类和 VolumePriceSignalGenerator 类，不涉及存储层和数据采集层。

**Tech Stack:** Python, NumPy, Pandas

## Global Constraints

- DataManager 唯一数据网关，不绕过
- 属于策略核算，用户触发
- 不引入外部依赖

---

### Task 8: 极端信号改用历史极值

**Files:**
- Modify: `backend/app/engine/framework/volume_price_strategy.py` — VPStateMachine.classify_fast()

- [ ] **Step 1: 修改 classify_fast() 中的极端信号判定**

```python
# 当前（固定倍数）:
if vol_ratio > 2.5 and price_chg_1d > 6:
    return VP_EXTREME_BULL
if vol_ratio < 0.4 and price_chg_1d < -6:
    return VP_EXTREME_BEAR

# 改为（历史极值）:
if len(volumes) >= 60:
    vol_60d_max = float(np.max(volumes[-60:]))
    vol_60d_min = float(np.min(volumes[-60:]))
    price_20d_max = float(np.max(closes[-20:]))
    price_20d_min = float(np.min(closes[-20:]))
    if volumes[-1] >= vol_60d_max and closes[-1] >= price_20d_max:
        return VP_EXTREME_BULL
    if volumes[-1] <= vol_60d_min and closes[-1] <= price_20d_min:
        return VP_EXTREME_BEAR
```

- [ ] **Step 2: 验证语法正确**

```bash
python -c "import py_compile; py_compile.compile('backend/app/engine/framework/volume_price_strategy.py', doraise=True); print('OK')"
```

---

### Task 9: 背离预警条件修正

**Files:**
- Modify: `backend/app/engine/framework/volume_price_strategy.py` — VPStateMachine.classify_fast()

- [ ] **Step 1: 修改背离预警判定条件**

当前顶背离条件：`volumes[-i] < vol_ma5 * 0.8`
改为：`volumes[-i] < vol_ma5` （去掉 0.8 乘数）

当前底背离条件：`volumes[-i] > vol_ma5 * 1.3`（用 vol_ma5 替代原来的 vol_ma5 判断，原来代码已经是 vol_ma5*1.3，改为 vol_ma5*1.3 不变）
改为：`volumes[-i] > vol_ma5 * 1.3`（确认逻辑正确）

实际上原代码底背离用的是 `vol_low_3d` 变量重复使用了，需要修正为独立的变量名和条件。

```python
# 顶背离
price_high_condition = closes[-1] >= max(closes[-10:-1]) if len(closes) >= 10 else False
vol_low_3d = all(volumes[-i] < vol_ma5 for i in range(1, 4)) if len(volumes) >= 4 else False
if price_high_condition and vol_low_3d:
    return VP_DIVERGE_BULL

# 底背离（独立变量，不与顶背离共用）
price_low_condition = closes[-1] <= min(closes[-10:-1]) if len(closes) >= 10 else False
vol_high_3d = all(volumes[-i] > vol_ma5 * 1.3 for i in range(1, 4)) if len(volumes) >= 4 else False
if price_low_condition and vol_high_3d:
    return VP_DIVERGE_BEAR
```

- [ ] **Step 2: 验证语法正确**

---

### Task 10: 连续确认切换

**Files:**
- Modify: `backend/app/engine/framework/volume_price_strategy.py` — VolumePriceSignalGenerator.generate()

- [ ] **Step 1: 在 generate() 中检查连续 2 天一致性**

```python
# 在确定 direction 之后、返回 VolumePriceSignal 之前注入检查
# 检查状态机历史：如果前一天的状态和当前状态方向不同，降低置信度
sm_history = self.state_machine._fast_history
if len(sm_history) >= 2:
    prev_state = sm_history[-2] if len(sm_history) >= 2 else None
    curr_state = sm_history[-1] if sm_history else None
    if prev_state and curr_state and prev_state != curr_state:
        prev_level = STATE_LEVEL_MAP.get(prev_state, "NEUTRAL")
        curr_level = STATE_LEVEL_MAP.get(curr_state, "NEUTRAL")
        if prev_level != curr_level:
            # 方向变化但未连续确认，降低置信度
            conf *= 0.85
            evidence.append(f"【状态切换】{prev_state[:6]}→{curr_state[:6]}，连续确认中")
```

- [ ] **Step 2: 验证语法正确**

---

### Task 11: 显式状态转换规则

**Files:**
- Modify: `backend/app/engine/framework/volume_price_strategy.py` — VPStateMachine

- [ ] **Step 1: 新增 check_transition() 方法**

```python
def check_transition(self, closes: np.ndarray, volumes: np.ndarray,
                     current_state: str) -> Optional[Dict]:
    """检查显式状态转换规则（3 条）

    Returns:
        None 表示无转换触发，dict 表示触发的转换信息
    """
    if len(closes) < 5 or len(volumes) < 5:
        return None
    vol_ma5 = float(np.mean(volumes[-5:])) if len(volumes) >= 5 else 0
    ma60 = float(np.mean(closes[-60:])) if len(closes) >= 60 else closes[-1]
    price_chg = (closes[-1] / closes[-2] - 1) * 100 if len(closes) >= 2 else 0
    vol_chg = (volumes[-1] / volumes[-2] - 1) * 100 if len(volumes) >= 2 else 0

    # 规则1: 价跌量缩(健康) → 价跌量增(底背离)
    if current_state == VP_HEALTHY_BEAR:
        vol_incr_3d = all(volumes[-i] > volumes[-i-1] for i in range(1, 4)) if len(volumes) >= 4 else False
        if vol_incr_3d and closes[-1] < ma60 * 0.97:
            return {'from': current_state, 'to': VP_DIVERGE_BEAR,
                    'reason': '成交量连续3日放大+跌破MA60'}

    # 规则2: 价涨量增(强势) → 价涨量缩(顶背离)
    if current_state == VP_HEALTHY_BULL:
        vol_decr_3d = all(volumes[-i] < volumes[-i-1] for i in range(1, 4)) if len(volumes) >= 4 else False
        price_slow = all(abs((closes[-i] / closes[-i-1] - 1)) < 0.005 for i in range(1, 4)) if len(closes) >= 4 else False
        if vol_decr_3d and price_slow:
            return {'from': current_state, 'to': VP_DIVERGE_BULL,
                    'reason': '量缩价平连续3日'}

    # 规则3: 价跌量增(底背离) → 观察入场
    if current_state == VP_DIVERGE_BEAR:
        vol_ratio = volumes[-1] / max(vol_ma5, 1e-9)
        if vol_ratio > 1.5 and price_chg > 0:
            return {'from': current_state, 'to': VP_HEALTHY_BULL,
                    'reason': '放量止跌，入场窗口开启'}

    return None
```

- [ ] **Step 2: 在 define() 中调用 check_transition() 并注入结果到返回值**

```python
# 在 define() 中的 update_fast() 之后添加
transition = self.check_transition(closes, volumes, fast_state)
result['transition'] = transition
```

- [ ] **Step 3: 验证语法正确**

---

### Task 12: 转换信息加入证据

**Files:**
- Modify: `backend/app/engine/framework/volume_price_strategy.py` — VolumePriceSignalGenerator.generate()

- [ ] **Step 1: 在 generate() 中读取 transition 信息加入 evidence**

```python
# 在构建 evidence 时
transition = sm_result.get('transition')
if transition:
    evidence.append(f"【状态转换】{transition['reason']}")
```

- [ ] **Step 2: 验证语法正确**

---

### Task 13: 集成测试 + 验证

- [ ] **Step 1: 重启服务器**
```bash
ps aux | grep run.py | grep -v grep | awk '{print $2}' | xargs kill
sleep 2
DATA_DAEMON_RUNNING=1 python run.py --port 5001 &
sleep 10
```

- [ ] **Step 2: 测试策略分析端点**
```bash
curl -s -X POST http://localhost:5001/api/v3/strategy/analyze \
  -H 'Content-Type: application/json' \
  -d '{"ts_code":"000002.SZ"}' | python3 -c "
import sys, json
d = json.load(sys.stdin)
vp = d['data']['dimensions']['volume_price']
print('状态:', vp.get('phase_label'))
print('方向:', vp.get('direction'))
print('置信度:', vp.get('trend_strength'))
"
```

- [ ] **Step 3: 验证 evidence 中包含状态转换信息**
```bash
curl -s -X POST http://localhost:5001/api/v3/strategy/analyze \
  -H 'Content-Type: application/json' \
  -d '{"ts_code":"000002.SZ"}' | python3 -c "
import sys, json
d = json.load(sys.stdin)
ev = d['data']['dimensions']['volume_price'].get('status_text', '')
print('证据:', ev[:200] if ev else 'N/A')
"
```
