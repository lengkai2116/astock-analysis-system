# Task 3-5 提示汇总

## Task 3: 实现预跌型 20 种形态检测器

### Intent
**[S1] 形态覆盖度**: 基于 Wiki 50 种量价形态，实现预跌型 20 种形态检测器。

### Files
- Create: `backend/app/engine/patterns/detectors/bearish_patterns.py`
- Create: `backend/tests/test_bearish_patterns.py`

### 关键点
- 继承 `PatternDetector` 基类
- 实现 20 种预跌型形态检测逻辑
- 参考《量价狙击》第七章

### 测试要求
- 初始化测试
- 返回列表测试
- 空数据测试
- 数据不足测试

---

## Task 4: 实现黑马型 10 种形态检测器

### Intent
**[S1] 形态覆盖度**: 基于 Wiki 50 种量价形态，实现黑马型 10 种形态检测器。

### Files
- Create: `backend/app/engine/patterns/detectors/blackhorse_patterns.py`
- Create: `backend/tests/test_blackhorse_patterns.py`

### 关键点
- 继承 `PatternDetector` 基类
- 实现 10 种黑马型形态检测逻辑
- 参考《量价狙击》第八章

### 测试要求
- 初始化测试
- 返回列表测试
- 空数据测试

---

## Task 5: 实现四类八种状态检测器

### Intent
**[S2] 动态状态感知**: 基于 Wiki 四类八种量价状态，实现状态检测器。

### Files
- Create: `backend/app/engine/patterns/detectors/state_detectors.py`
- Create: `backend/tests/test_state_detectors.py`

### 关键点
- 继承 `PatternDetector` 基类
- 实现 8 种状态检测逻辑
- 参考 Wiki 动态量价状态感知策略

### 四类八种状态
1. 价涨量增（健康动量）
2. 价跌量缩（健康动量）
3. 价涨量缩（背离预警）
4. 价跌量增（背离预警）
5. 天量天价（极端信号）
6. 地量地价（极端信号）
7. 放量突破（筹码转换）
8. 缩量回踩（筹码转换）

### 测试要求
- 初始化测试
- 返回列表测试
- 空数据测试
- 单个状态检测测试
