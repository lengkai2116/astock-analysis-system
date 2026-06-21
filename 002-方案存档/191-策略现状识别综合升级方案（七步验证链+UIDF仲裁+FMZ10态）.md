---
title: 策略现状识别综合升级方案（七步验证链+UIDF仲裁+FMZ 10态）
type: 实施方案
date: 2026-06-21
---

# 策略现状识别综合升级方案

## 一、背景与目的

经186号方案四个波段的策略系统升级后（P0-P3共54/68项已完成），系统具备了完整的策略计算能力。但**现状识别的输出结构和决策链路**仍停留在"扁平共识→简单加权"的水平，未充分利用知识库中的七步分析法、UIDF仲裁机制和FMZ 10种市场状态。

本次升级针对三个核心改进点：

| 改进点 | 当前问题 | 目标 |
|--------|---------|------|
| **#64 FMZ 10态** | 市场状态仅4种（TRENDING_BULL/BEAR/RANGING/HIGH_VOL），精度不足 | 扩展至10种，动态权重矩阵精度翻倍 |
| **#65 七步验证链** | StatusOutputService仅做扁平共识聚合（数票），没有"多层验证相互制约" | 改为3层4验证链结构，降低假信号率 |
| **#66 UIDF+AI仲裁** | UIDF仅做线性加权（UPF 0.6+AI 0.4），AI输入扁平化输出刻板 | AI作为冲突仲裁者，联动LLM Wiki知识库 |

---

## 二、#64 FMZ 10种市场状态扩展

### 2.1 当前状态

`StageDetector.recognize_market_condition()` (`volume_price_strategy.py`) 只有4种状态判定，`StateDependentFactorWeight` (`state_dependent_factor_weight.py`) 只有4行权重矩阵。

### 2.2 扩展方案

**FMZ 10种状态及量化判定条件**（全部基于现有OHLCV数据可计算）：

| 状态 | 判定条件 | 对应系统资源 |
|------|---------|------------|
| **TRENDING_BULL** (牛市) | 价格>EMA55, MACD线>信号线, RSI>50, 相对成交量>1 | 已有 |
| **TRENDING_BEAR** (熊市) | 价格<EMA55, MACD线<信号线, RSI<50, 成交量>均值 | 已有 |
| **RANGING** (侧向) | 价格与EMA55差值<ATR×0.5, ATR<20日均值 | 已有，改名为RANGING |
| **HIGH_VOL** (波动) | ATR>20日均值×1.2 | 已有 |
| **MOMENTUM** (动量) | 价格变化>ATR×1.5, 成交量>20日均值×1.5 | **新增** |
| **MEAN_REV** (均值回归) | RSI>70或RSI<30 | **新增** |
| **BOX** (箱体) | RANGING且价格波动范围<20日均值×0.8 | **新增** |
| **MACRO** (宏观) | 价格变化绝对值>ATR×2 | **新增** |
| **WOLF** (狼-恐慌) | 收盘涨跌幅<-3%, 且价格<EMA55 | **新增** |
| **EAGLE** (鹰-健康牛) | TRENDING_BULL且ATR<20日均值×0.8 | **新增** |

### 2.3 判定优先级

10种状态非互斥，按以下优先级裁决（从高到低）：

```
WOLF > MACRO > MEAN_REV > MOMENTUM > BOX > RANGING > HIGH_VOL > EAGLE > TRENDING_BULL > TRENDING_BEAR
```

### 2.4 StateDependentFactorWeight 扩展

从4行→10行的权重矩阵扩展（关键在新6种状态的权重分配）：

| 状态 | 动量因子 | 反转因子 | 情绪因子 | 筹码因子 | 特征 |
|------|---------|---------|---------|---------|------|
| TRENDING_BULL | 0.35→**0.40** | 0.15→**0.10** | 0.25 | 0.25→**0.20** | 牛市更偏动量 |
| TRENDING_BEAR | 0.10 | 0.40→**0.45** | 0.20→**0.15** | 0.30 | 熊市更偏防御 |
| RANGING | 0.20→**0.15** | 0.30→**0.35** | 0.20 | 0.30 | 震荡偏反转 |
| HIGH_VOL | 0.20→**0.15** | 0.20→**0.15** | **0.50** | 0.20→**0.15** | 高波动极偏情绪 |
| **MOMENTUM** | **0.60** | **0.05** | 0.20 | 0.15 | 动量阶段不逆向 |
| **MEAN_REV** | 0.05 | **0.65** | 0.15 | 0.15 | 均值回归极偏反转 |
| **BOX** | 0.10 | 0.30 | 0.20 | **0.40** | 箱体偏筹码位置 |
| **MACRO** | 0.15 | 0.15 | **0.50** | 0.20 | 宏观事件偏情绪 |
| **WOLF** | 0.05 | **0.50** | 0.25 | 0.20 | 恐慌极偏反转+避险 |
| **EAGLE** | **0.45** | **0.15** | 0.20 | 0.20 | 健康牛偏动量趋势 |

### 2.5 涉及文件

| 操作 | 文件 |
|------|------|
| 修改 | `backend/app/engine/framework/volume_price_strategy.py` — StageDetector.recognize_market_condition() |
| 修改 | `backend/app/engine/framework/state_dependent_factor_weight.py` — WEIGHT_MATRIX 10行 |
| 修改 | `backend/app/services/signal_computation_service.py` — compute_for_stock() 传递mapped市场状态 |

---

## 三、#65 七步分析验证链重构 StatusOutputService

### 3.1 当前问题

`StatusOutputService.aggregate()` 目前是扁平共识聚合：

```python
def aggregate(self, signals):
    # 就是投票统计
    consensus = majority_vote(status_list)  # 谁票多
    risk = max(risk_levels)                 # 取最高风险
    momentum = count_votes(...)             # 数票
    # 完全没有"验证"的概念
```

这样输出的结果**没有经过交叉验证**，假信号率不会因为多策略而降低。

### 3.2 重构后的三层架构

```
第一层：维度证据层（6个独立策略的现状输出）
  ├── 缠论结构  → 中枢/背驰/买卖点
  ├── 筹码主力  → 分布/集中度/动向
  ├── 情绪环境  → 快线/慢线/板块轮动
  ├── 多因子    → 动量/反转/价值评分
  ├── 量价形态  → 形态匹配/量价关系
  └── 基本面    → PE/PB/ROCE（暂缺，标记为占位）

第二层：多维交叉验证层（4条验证链）
  ├── 链1: 筹码+量价 → 确认主力行为的真伪
  ├── 链2: 缠论+因子 → 结构位置验证因子倾向
  ├── 链3: 情绪+基本面 → 外部情绪与内在价值对照
  └── 链4: 技术面(1-2-6) vs 基本面(5) → 技术面与基本面共振检查

第三层：现状输出层（带验证链评级的统一输出）
  ├── status: 最终状态判定 + 综合置信度
  ├── verification_chain: 4条链通过/冲突详情
  ├── dimensions: 6维度各自现状
  └── conflicts_needing_ai: 待AI仲裁的冲突项
```

### 3.3 四条验证链的编码规则

**链1：筹码+量价（主力行为验证）**
```
条件：chip.state == "ACCUMULATING" 且 volume_price.volume.state 含"放量"
→ 结果：主力行为被量价验证通过，confidence 放大 1.15x
条件：chip.state == "ACCUMULATING" 但 volume_price.volume.state 含"缩量"
→ 结果：主力行为未得到量价验证，标记 warning
条件：chip.state == "DISTRIBUTING" 且 volume_price.volume.state 含"放量"
→ 结果：主力出货被确认
```

**链2：缠论+因子（结构位置验证）**
```
条件：price_position 位于 zhongshu_upper 之上 且 momentum因子 > 0.6
→ 结果：趋势延续结构，验证通过
条件：price_position 位于 zhongshu_inside 且 reversal因子 > 0.6
→ 结果：中枢内反转预期，验证通过
条件：price_position 位于 zhongshu_upper 之上 但 reversal因子 > 0.6
→ 结果：结构看涨但因子看反转 → 冲突，标记待AI仲裁
```

**链3：情绪+基本面（外部环境验证）**
```
条件：bociasi 快线 bullish 且 PE < 20（估值偏低）
→ 结果：情绪回暖有基本面支撑，强验证
条件：bociasi 快线 bullish 但 PE > 50（估值偏高）
→ 结果：情绪回暖但估值偏高 → 冲突，标记
条件：bociasi 慢线 bearish 且板块轮动 WEAKENING
→ 结果：宏观面共振看空
```

**链4：技术面+基本面（全面共振验证）**
```
条件：D1-D3(缠论+筹码+量价) 中 ≥2个看涨 且 D5(基本面) 健康
→ 结果：技术面与基本面共振
条件：D1-D3 看涨 但 D5 有财务风险
→ 结果：技术面好但基本面有硬伤，仓位限制 30%
条件：D1-D3 看跌 且 D5 恶化
→ 结果：全维度看空，强烈卖出
```

### 3.4 输出结构

```python
@dataclass
class VerificationChainResult:
    chain_id: str              # "chip_volume" / "chanlun_factor" / "emotion_fundamental" / "technical_fundamental"
    passed: bool               # 验证是否通过
    confidence_multiplier: float  # 置信度乘数 (0.5-1.2)
    conflict_detail: str = ""  # 冲突详细说明
    evidence: List[str] = field(default_factory=list)

@dataclass  
class StatusOutputV2:
    """七步分析验证链输出（替代原来的扁平status_recognition）"""
    # 第一层：维度证据
    dimensions: Dict
    # 第二层：验证链结果
    verification_chains: List[VerificationChainResult]
    # 第三层：最终状态
    state: str
    confidence: float
    chain_passed_ratio: float      # 通过链比例 (2/4, 3/4, 4/4)
    conflicts_for_ai: List[Dict]   # 待AI仲裁的冲突
```

### 3.5 涉及文件

| 操作 | 文件 |
|------|------|
| 重写 | `backend/app/services/status_output_service.py` — 新增验证链方法+StatusOutputV2 |
| 微调 | `backend/app/routes/ai_analysis.py` — status-interpret端点适配新输出 |

---

## 四、#66 UIDF+AI仲裁联动改造

### 4.1 当前问题

当前 `UIDFEngine.consolidate()` 仅做线性加权，完全未利用AI的语义理解能力：

```python
fv = upf_signal * upf_conf * 0.6 + ai_signal * ai_conf * 0.4
```

当前的 `interpret_status()` （`deepseek_analysis_service.py:540-606`）只接收扁平文本，输出固定模板的JSON，且全部是Mock降级。

### 4.2 改造方案：三层AI输入

**第一层：七步验证链的待仲裁冲突**

AI不再接收"股票状态聚合数据"，而是接收**需要AI仲裁的冲突点**：

```
输入 → AI输出 → 作为加权输入参与最终决策
        ↑
  仅有"需要仲裁"的冲突项才发给AI
```

**第二层：LLM Wiki知识库概念映射**

在 `ai_context_builder.py` 中新增知识库概念匹配引擎：

```python
class WikiConceptMatcher:
    """将当前股票现状映射到LLM Wiki知识库概念"""
    
    def match(self, status: Dict, market_state: str) -> List[Dict]:
        """
        根据当前状态匹配知识库概念
        
        逻辑：
        - market_state == 'MOMENTUM' → 匹配「三线开花」「主升浪特征」
        - market_state == 'WOLF' → 匹配「恐慌底」「情绪冰点」
        - price_position == 'zhongshu_lower' + divergence_detected → 匹配「中枢下沿背驰买点」
        - chip.state == 'ACCUMULATING' → 匹配「主力建仓期特征」
        """
        concepts = []
        # ...匹配逻辑
        return concepts
```

**第三层：AI提示重构**（不再问"这个股票怎么样"，而是以下结构）：

```
system_prompt = f"""
你是一名A股投资策略的AI仲裁者。
你的任务不是分析数据，而是对策略系统产生的以下冲突进行仲裁判决。

【当前市场环境】
market_state: {market_state}
解读：{market_state_description}

【未解决的验证链冲突】
{json.dumps(conflicts_for_ai, ensure_ascii=False, indent=2)}

【知识库相关准则】
{json.dumps(matched_concepts, ensure_ascii=False, indent=2)}

请对每个冲突给出仲裁意见：
1. 该冲突的性质（共存的矛盾 还是 需要取舍的矛盾）
2. 你的偏向建议（偏向哪一侧，为什么不偏向另一侧）
3. 如果偏向，confidence调整建议值
4. 引用知识库准则中的具体依据

输出JSON格式：
{{
    "arbitrations": [
        {{
            "conflict_id": str,
            "nature": "共存/取舍",
            "preference": str,
            "confidence_adjustment": float,
            "reasoning": str,
            "wiki_reference": str
        }}
    ],
    "summary": str
}}
"""
```

### 4.3 最终决策流

```
七步验证链输出（含冲突）
    │
    ├── chain_passed_ratio >= 75%（验证链通过≥3/4）
    │   └──→ 直接使用验证链结果，AI仅做摘要
    │
    ├── 25% < chain_passed_ratio < 75%（需要AI仲裁）
    │   └──→ 冲突项发送给AI → AI仲裁结果加权到最终决策
    │
    └── chain_passed_ratio <= 25%（验证链基本未通过）
        └──→ 全部信息发送给AI做综合分析
```

这种设计避免了"无脑调用AI"——**大多数情况(≥3/4通过)不需要AI介入**，仅在有真实冲突时才调用AI作为仲裁者。这既减少了API调用成本，又让AI只做它擅长的事。

### 4.4 涉及文件

| 操作 | 文件 |
|------|------|
| 增强 | `backend/app/engine/framework/unified_investment_decision_framework.py` — UIDFEngine增加conflict仲裁模式 |
| 增强 | `backend/app/services/deepseek_analysis_service.py` — interpret_status改为接收验证链冲突 |
| 增强 | `backend/app/services/ai_context_builder.py` — 新增WikiConceptMatcher |
| 增强 | `backend/app/routes/ai_analysis.py` — status-interpret端点整合新流程 |

---

## 五、依赖关系

```
#64 (FMZ 10态) ─────────── 独立（仅改recognize_market_condition + 权重矩阵）
                            ↓
#65 (七步验证链) ─────────  依赖 #64（验证链链3用到了新增的MOMENTUM/BOX等状态）
                            ↓
#66 (UIDF+AI仲裁) ───────  依赖 #65（AI仲裁的"冲突"来自验证链输出）
```

执行顺序：#64 先行 → #65 并行 → #66 最后

---

## 六、涉及文件清单

| 操作 | 文件 | 规模 |
|------|------|------|
| 修改 | `backend/app/engine/framework/volume_price_strategy.py` | +~80行FMZ 10态判定 |
| 修改 | `backend/app/engine/framework/state_dependent_factor_weight.py` | +~30行权重矩阵 |
| 重写 | `backend/app/services/status_output_service.py` | +~200行验证链 |
| 增强 | `backend/app/engine/framework/unified_investment_decision_framework.py` | +~80行仲裁模式 |
| 增强 | `backend/app/services/ai_context_builder.py` | +~100行WikiConceptMatcher |
| 增强 | `backend/app/services/deepseek_analysis_service.py` | +~60行仲裁提示 |
| 微调 | `backend/app/services/signal_computation_service.py` | +~20行市场状态传递 |
| 微调 | `backend/app/routes/ai_analysis.py` | +~20行适配 |

---

## 七、验证方法

| 文件 | 验证方法 |
|------|---------|
| volume_price_strategy.py | `python3 -c "compile(open('...').read(), '...', 'exec')"` |
| state_dependent_factor_weight.py | 同上 |
| 新建文件 | python3 -c "from app.engine.framework.status_output_v2 import *" |
| 全部 | 逐文件AST解析 |
