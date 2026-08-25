# Task 7-12 完整提示汇总

## Task 7: pattern_score_cache 表和 DataManager 接口

### Intent
**[S4] 缓存策略**: 遵循 353/358 号方案架构红线，日终批量计算 + 缓存。

### Files
- Modify: `backend/app/data/__init__.py`
- Create: `backend/tests/test_pattern_score_cache.py`

### 实现要点
1. 在 DataManager 类中添加 `cache_pattern_score()` 和 `get_pattern_score()` 方法
2. 创建测试验证接口

---

## Task 8: 注册日终批量计算到 data_daemon

### Intent
**[S4] 计算时机**: 遵循 353/358 号方案架构红线，日终批量计算 + 缓存。

### Files
- Modify: `backend/app/data_daemon.py`

### 实现要点
1. 添加 `_batch_pattern_score()` 函数
2. 注册到日终同步

---

## Task 9: 集成到 dim3_vp_engine

### Intent
**[S5] 集成到 health_score**: 保持 15% 权重集成到 health_score。

### Files
- Modify: `backend/app/opportunity_atlas/dimensions/dim3_vp_engine.py`

### 实现要点
1. 导入 PatternEngine
2. 替换原有 KLinePatternVerifier
3. 集成到 health_score（15% 权重）

---

## Task 10: 完整测试套件

### Intent
**[S6] 测试覆盖**: 完整测试套件，确保质量。

### Files
- Create: `backend/tests/test_pattern_integration.py`

### 实现要点
1. 集成测试：检测 → 聚合 → 缓存 → 集成
2. 分数范围测试
3. 详情结构测试

---

## Task 11: 重构 kline_adapter.py

### Intent
**[S7] 代码整合**: 重构适配器，保持向后兼容。

### Files
- Modify: `backend/app/engine/patterns/adapters/kline_adapter.py`

### 实现要点
1. 使用 PatternEngine 替代原有逻辑
2. 保持原有接口不变

---

## Task 12: 添加 STATE 分类

### Intent
**[S2] 动态状态感知**: 添加 STATE 分类到 PatternCategory。

### Files
- Modify: `backend/app/engine/patterns/__init__.py`
- Modify: `backend/app/engine/patterns/registry.py`

### 实现要点
1. 添加 STATE 到 PatternCategory 枚举
2. 更新注册表中的状态分类

---

## 执行顺序建议

1. Task 2-5: 并行实现四种检测器
2. Task 6: 创建 PatternEngine（依赖 Task 2-5）
3. Task 7-8: 缓存和计算时机（独立）
4. Task 9: 集成到 dim3_vp_engine（依赖 Task 6）
5. Task 10: 测试（依赖所有任务）
6. Task 11: 重构适配器（依赖 Task 6）
7. Task 12: 添加 STATE 分类（独立）
