# Task 9-12 实现提示

## Task 9: 集成到 dim3_vp_engine

### Intent
**[S5] 集成到 health_score**: 保持 15% 权重集成到 health_score。

### Files
- Modify: `backend/app/opportunity_atlas/dimensions/dim3_vp_engine.py`

### 实现要点

1. 导入 PatternEngine
2. 初始化 PatternEngine
3. 替换原有 KLinePatternVerifier
4. 集成到 health_score（15% 权重）

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

## Commit
```bash
# Task 9
git add app/opportunity_atlas/dimensions/dim3_vp_engine.py
git commit -m "feat(dim3): integrate PatternEngine with 15% weight"

# Task 10
git add tests/test_pattern_integration.py
git commit -m "test(patterns): add comprehensive integration tests"

# Task 11
git add app/engine/patterns/adapters/kline_adapter.py
git commit -m "refactor(adapter): use PatternEngine in KLinePatternAdapter"

# Task 12
git add app/engine/patterns/__init__.py app/engine/patterns/registry.py
git commit -m "feat(patterns): add STATE category for dynamic states"
```
