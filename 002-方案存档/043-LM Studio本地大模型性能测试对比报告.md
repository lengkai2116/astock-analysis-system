# LM Studio 本地大模型性能测试对比报告

## 📊 测试总结

### 测试环境
- **测试时间**：2026-05-16
- **测试工具**：LM Studio 本地服务器
- **API 地址**：http://localhost:1234

---

## 🤖 模型对比总览

| 指标 | qwen3.5-9b | gemma-4-26b-a4b | 推荐 |
|------|-----------|----------------|------|
| **参数量** | 9B | 26B | - |
| **平均速度** | ⚡ 10.4 tokens/秒 | ⚡⚡⚡ **31.4 tokens/秒** | ⭐ gemma |
| **平均耗时** | 54.03秒 | **18.70秒** | ⭐ gemma |
| **中文支持** | ✅ **优秀** | ⚠️ 一般 | ⭐ qwen |
| **股票分析质量** | ✅ **优秀**（中文） | ✅ 优秀（英文） | 持平 |
| **稳定性** | ✅ 稳定 | ✅ 稳定 | 持平 |
| **显存要求** | 8-16GB（低） | 24-32GB（高） | ⭐ qwen |

---

## 📈 详细测试结果

### 测试1：简单问题

**问题**：`你好，请介绍一下你自己。`

| 模型 | 耗时 | 速度 | 输出Token | 结果 |
|------|------|------|----------|------|
| **qwen3.5-9b** | 48.93秒 | 6.9 tokens/秒 | 337 | ✅ 通过 |
| **gemma-4-26b-a4b** | 8.52秒 | **30.3 tokens/秒** | 258 | ✅ 通过 |

**分析**：
- **gemma 速度快 4.4倍**（30.3 vs 6.9 tokens/秒）
- gemma 回答简洁，qwen 回答详细

---

### 测试2：股票分析

**问题**：分析股票（000001.SZ，资产负债率17.74%，ROE 10.64%，净现金是）

| 模型 | 耗时 | 速度 | 输出Token | 结果 |
|------|------|------|----------|------|
| **qwen3.5-9b** | 13.13秒 | 11.6 tokens/秒 | 152 | ✅ 通过 |
| **gemma-4-26b-a4b** | 21.94秒 | **32.2 tokens/秒** | 707 | ✅ 通过 |

**分析**：
- **gemma 速度快 2.8倍**（32.2 vs 11.6 tokens/秒）
- qwen 输出更专业（中文分析）
- gemma 输出更详细（英文分析，表格展示）

#### qwen3.5-9b 分析结果（中文）
```
**评估结论：**
深圳发展银行呈现典型的"高成长、低杠杆"特征。资产负债率仅17.74%远低于银行业平均水平，显示极强的抗风险能力和资产安全性。

**投资建议：**
该股基本面极其稳健，适合风险偏好较低、追求长期稳定分红的投资者配置。
```

#### gemma-4-26b-a4b 分析结果（英文）
```
Overall Verdict: [BUY / HOLD]
Recommendation: Hold/Accumulate.
Reasoning: The combination of low leverage (17.74%) and moderate, steady ROE (10.64%) makes this a "Defensive Growth" play.

Final Conclusion: This entity exhibits high financial health and moderate profitability, making it a low-risk, medium-reward asset.
```

---

### 测试3：复杂推理

**问题**：分析"资产负债率<20%，ROE>15%，现金流充沛，但行业景气度下降"的投资价值

| 模型 | 耗时 | 速度 | 输出Token | 结果 |
|------|------|------|----------|------|
| **qwen3.5-9b** | 100.05秒 | 12.6 tokens/秒 | 1263 | ✅ 通过 |
| **gemma-4-26b-a4b** | 25.64秒 | **31.8 tokens/秒** | 816 | ✅ 通过 |

**分析**：
- **gemma 速度快 2.5倍**（31.8 vs 12.6 tokens/秒）
- qwen 输出更详细（1263 vs 816 tokens）
- 两者分析质量都很高，逻辑清晰

#### qwen3.5-9b 深度分析要点
```
1. 核心矛盾诊断：高ROE的来源是什么？
2. "防御性"资产的价值重估
3. 竞争格局与护城河的考验
4. 估值逻辑的切换：从PEG到DCF
5. 潜在的风险点（Red Flags）
```

#### gemma-4-26b-a4b 深度分析要点
```
1. Financial Dimension (The Bull Case)
2. Macroeconomic Dimension (The Risk of the "Downturn")
3. Strategic Dimension (Operational Value)
4. Risk Assessment (The Bear Case)
```

---

## 🎯 最终推荐

### 🥇 首选推荐：qwen3.5-9b

**理由**：
1. ✅ **中文支持优秀**：原生中文，对中国股票分析场景非常友好
2. ✅ **显存要求低**：8-16GB 即可流畅运行
3. ✅ **性能足够**：完全满足股票分析需求
4. ✅ **成本低**：对硬件要求低，适用范围广

**适用场景**：
- 📈 中国A股股票分析（中文报告）
- 💼 日常筛选和评估
- 📊 快速响应需求

---

### 🥈 备选推荐：gemma-4-26b-a4b

**理由**：
1. ⚡ **速度更快**：31.4 tokens/秒，是 qwen 的 3倍
2. ✅ **分析能力强**：MoE架构，复杂推理优秀
3. ✅ **多语言支持**：英文分析非常专业

**适用场景**：
- 📑 深度分析报告（英文）
- 🔬 复杂投资研究
- 💡 高端投研需求

---

## 💡 使用建议

### 日常使用（强烈推荐 qwen3.5-9b）

```python
# 配置
MODEL = "qwen/qwen3.5-9b"

# 优势
- 中文友好
- 显存要求低
- 速度足够（10+ tokens/秒）
- 完全满足日常股票分析需求
```

### 深度研究（可选 gemma-4-26b-a4b）

```python
# 配置
MODEL = "gemma-4-26b-a4b-it-i1"

# 优势
- 速度快（30+ tokens/秒）
- 分析更深入
- 适合英文报告
```

---

## 📋 技术集成

### 已创建的对接脚本

**文件**：`/Users/kalence/Desktop/测试/stock_analyzer_desktop/server/screening/lm_studio_integration.py`

**使用方式**：
```python
from lm_studio_integration import chat_completion

result = chat_completion(
    messages=[
        {"role": "system", "content": "你是专业的股票分析师..."},
        {"role": "user", "content": "请分析这只股票..."}
    ],
    model="qwen/qwen3.5-9b",  # 选择模型
    stream=False
)

if result['success']:
    print(result['content'])
```

---

## ✅ 结论

### 推荐最终选择：qwen3.5-9b（首选）

**核心理由**：
1. ✅ 中文支持优秀，对中国股票市场分析更友好
2. ✅ 显存要求低（8-16GB），硬件门槛低
3. ✅ 性能足够，完全满足股票分析需求
4. ✅ 完全免费，无需额外成本

**gemma-4-26b-a4b 作为备选**：
- 适合深度研究
- 适合英文报告需求
- 需要更高硬件配置

---

**报告生成时间**：2026-05-16  
**测试状态**：✅ 完成  
**推荐模型**：qwen/qwen3.5-9b（首选）
