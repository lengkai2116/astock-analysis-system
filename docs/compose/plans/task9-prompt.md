# Task 9 提示：集成到 dim3_vp_engine

## Intent (from spec)

**[S5] 集成到 health_score**: 保持 15% 权重集成到 health_score。

**Scope boundary:** This task covers ONLY integrating PatternEngine into dim3_vp_engine. Do NOT implement caching (Tasks 7-8) or testing (Task 10).

## Task Description

**Covers:** [S5] 集成到 health_score

**Files:**
- Modify: `backend/app/opportunity_atlas/dimensions/dim3_vp_engine.py`

**Interfaces:**
- Consumes: `PatternEngine.evaluate()`
- Produces: 15% 权重集成到 health_score

**Step 1: 修改 dim3_vp_engine.py**

在 `backend/app/opportunity_atlas/dimensions/dim3_vp_engine.py` 中：

```python
# 1. 在文件开头添加导入
from app.engine.patterns.engine import PatternEngine

# 2. 在 Dim3VPEngine 类中初始化引擎
class Dim3VPEngine:
    def __init__(self):
        # ... 现有初始化代码 ...
        self.pattern_engine = PatternEngine()

    # 3. 在 evaluate() 方法中调用新引擎
    def evaluate(self, df: pd.DataFrame, context: Dict) -> Dict:
        # ... 现有代码 ...

        # 计算形态评分（替代原有 KLinePatternVerifier）
        pattern_score, pattern_details = self.pattern_engine.evaluate(df, context)

        # 4. 集成到 health_score（保持 15% 权重）
        # 原有逻辑：raw += (pattern_score - 50) / 50 * 1.5
        # 新逻辑：从 10 分制映射
        pattern_deviation = (pattern_score - 5) / 5 * 1.5
        raw += pattern_deviation

        # ... 其余代码 ...
```

**Step 2: 运行现有测试验证集成**

```bash
cd /Users/kalence/Desktop/01-A股股票分析系统/backend
pytest tests/test_dim3_vp_engine.py -v
```

Expected: 全部 PASS

**Step 3: Commit**

```bash
git add app/opportunity_atlas/dimensions/dim3_vp_engine.py
git commit -m "feat(dim3): integrate PatternEngine with 15% weight"
```

## Context

Task 6 已创建 PatternEngine。现在需要集成到 dim3_vp_engine，保持 15% 权重。

现有代码在 `dim3_vp_engine.py` 中已有 15% 权重集成，使用的是原有 KLinePatternVerifier。需要替换为新 PatternEngine。

## Before You Begin

If you have questions about:
- 现有 dim3_vp_engine 的结构
- 15% 权重的具体计算方式
- 与现有代码的集成方式

**Ask them now.**

## Your Job

Once you're clear on requirements:
1. Implement exactly what the task specifies
2. Verify integration works
3. Commit your work
4. Self-review
5. Report back

## Code Organization

- Follow existing patterns in the codebase
- Keep the integration minimal and focused
- Don't change other parts of dim3_vp_engine

## Before Reporting Back: Self-Review

Review your work:
- Did I correctly integrate PatternEngine?
- Is the 15% weight maintained?
- Does existing functionality still work?

## Report Format

When done, report:
- **Status:** DONE | DONE_WITH_CONCERNS | BLOCKED | NEEDS_CONTEXT
- What you implemented
- What you tested and test results
- Files changed
- Self-review findings
- Any issues or concerns
