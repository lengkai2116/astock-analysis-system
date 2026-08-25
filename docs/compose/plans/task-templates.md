# 任务提示模板

## Task 2-5 共同结构

### Intent
**[S1] 形态覆盖度**: 基于 Wiki 50 种量价形态，实现具体的形态检测器。

### Context
Task 1 已创建 `PatternDetector` 基类和注册了 50 种形态元数据。现在需要实现具体的检测逻辑。

### 共同步骤
1. 创建检测器文件
2. 实现检测方法（部分或全部）
3. 创建测试文件
4. 运行测试
5. Commit

### 共同接口
- 继承 `PatternDetector` 基类
- 实现 `detect(df, context)` 方法
- 返回 `List[PatternResult]`

---

## Task 6: PatternEngine

### Intent
**[S3] 聚合算法**: 实现 Wiki 10 分制聚合算法，统一调度所有检测器。

### Context
Task 2-5 已实现各种形态检测器。现在需要创建主入口统一调度并实现聚合逻辑。

### 关键点
- 聚合算法：5分基础 + 形态加分/减分 + 多形态共振加分
- 权重映射：基于 Wiki 星级
- 返回 `(score, details)` 元组

---

## Task 7-8: 缓存和计算时机

### Intent
**[S4] 缓存策略**: 遵循 353/358 号方案架构红线，日终批量计算 + 缓存。

### Context
架构红线：
- 计算时机：数据到达存储层的第一时间自动后台触发
- 禁止 API 路由中实时计算
- 结果写入缓存表，前端只读

---

## Task 9: 集成到 health_score

### Intent
**[S5] 集成到 health_score**: 保持 15% 权重集成到 health_score。

### Context
现有代码在 `dim3_vp_engine.py` 中已有 15% 权重集成。需要替换原有 KLinePatternVerifier 为新 PatternEngine。

### 关键修改
```python
# 原有：raw += (pattern_score - 50) / 50 * 1.5
# 新增：raw += (pattern_score - 5) / 5 * 1.5
```

---

## Task 10-12: 测试和重构

### Intent
**[S6] 测试覆盖**: 完整测试套件，确保质量。
**[S7] 代码整合**: 重构适配器，保持向后兼容。
