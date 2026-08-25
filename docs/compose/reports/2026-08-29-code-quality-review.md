# Code Quality Review 发现记录

## Task 1 审查发现（2026-08-29）

### 重要发现（需后续处理）

1. **registry.py 文件过大（401行）**
   - 问题：registry.py 混合了注册逻辑和批量数据
   - 建议：将 pattern 数据提取到单独的数据文件（如 wiki_patterns.py 或 JSON/YAML）
   - 优先级：中（在添加更多 pattern 前应处理）

2. **PatternDetector ABC 与现有适配器接口不匹配**
   - 问题：新 ABC 的 `detect(df, context)` 与现有适配器的 `detect_base_vp(closes, volumes)` 签名不一致
   - 建议：重构适配器使其符合 ABC，或使用适配器模式桥接
   - 优先级：低（可作为后续重构任务）

3. **测试文件使用 sys.path hack**
   - 问题：test_pattern_registry.py 使用 `sys.path.insert(0, ...)`
   - 建议：配置 pytest 的 `pythonpath` 或使用 editable install
   - 优先级：低（不影响功能，但影响代码质量）

### 次要发现

1. **`_calculate_volume_ma` 是多余的方法**
   - 问题：与 `_calculate_ma(df['volume'], window)` 完全相同
   - 建议：删除或标记为内部使用

2. **`min_periods` 值可能不准确**
   - 问题：所有 pattern 使用统一的 min_periods 值
   - 建议：在实现检测器时根据具体 pattern 调整

### 正面发现

1. **注册模式一致**：新 pattern 注册遵循现有模式
2. **ABC 设计简洁**：PatternDetector 只有 35 行，接口清晰
3. **包结构清晰**：detectors/ 与 adapters/ 并行组织
4. **测试覆盖全面**：17 个测试覆盖各种场景
5. **命名规范**：P-1-X, P-2-X, P-3-X, S-X 便于程序化处理

### 后续行动建议

1. 在 Task 6 完成后，考虑重构 registry.py
2. 在 Task 11 中处理适配器接口不匹配问题
3. 在 Task 10 中修复 pytest 配置问题
