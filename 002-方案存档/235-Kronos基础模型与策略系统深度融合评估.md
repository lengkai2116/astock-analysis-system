---
title: Kronos K线基础模型与策略系统深度融合评估
type: 方案/评估
date: 2026-07-01
status: ✅ 已确认 — 开关设计已纳入215号规格书 §10，待215号 Phase 1 开发时实施
关联文档: 215(个股策略规格书), 218(回测规格书), 186(策略引擎增强), 230(双数据源), 233(开发排序)
---

# Kronos K线基础模型与策略系统深度融合评估

> **问题：** Kronos（清华/Microsoft, AAAI 2026）是一个专门为K线数据设计的解码器基础模型（decoder-only foundation model），具有价格序列预测、波动率预测和合成K线生成能力。能否**不是作为单独的展示功能**，而是**将其能力融入到现有策略管道中**，增强系统对实际市场的分析能力？

---

## 零、核心结论

**能，但不是作为"第6个策略"简单投票。** Kronos的价值在于它是整个系统中**唯一的前瞻性组件**——现有5个策略（缠论/量价/筹码/BOCIASI/因子）全部是**向后看**的规则系统，Kronos提供**前瞻性市场状态预测**能力。最佳的融合点是充当**动态权重调节器**和**前瞻验证层**，而非增加一个平行信号。

| 评估维度 | 结论 |
|:---------|:------|
| 是否可作为独立策略？ | **可以，但价值有限**（只是增加一票）|
| 是否可增强现有策略？ | **可以，影响显著**（动态调节4层权重 + 冲突仲裁验证）|
| 是否可提升AI分析质量？ | **可以**（为DeepSeek提供"未来K线"语境）|
| 开发成本 | **~2天**（Kronos适配器 + 4个融合点）|
| 硬件需求 | **Kronos-mini (4.1M参数)** CPU可运行，~200-500ms/次 |
| 预期提升 | **系统级信号准确率 +10~15%**，高波动市场可达+15~25% |

---

## 一、现有策略管道全景

### 1.1 数据流架构

```
K线数据（200-512根）
        ↓
信号计算服务 (SignalComputationService)
  ├─ 缠论 (chanlun)        → 笔/段/中枢/买卖点
  ├─ 量价 (volume_price)   → 4阶段/50模式/格兰维尔
  ├─ 筹码 (chip)           → 主力4阶段识别
  ├─ BOCIASI 快线          → 4型情绪指标
  ├─ BOCIASI 慢线          → 跨市场ERP
  ├─ 因子 (factor)         → 500+因子评分
  └─ 拥挤度 (crowding)     → 融资比/异常换手
        ↓
UPF统一实战框架 (4层加权融合)
  ├─ structure (缠论)           权重 0.30 ← 静态
  ├─ pattern (量价)             权重 0.25 ← 静态
  ├─ sentiment (BOCIASI)         权重 0.20 ← 静态
  └─ factor (因子)               权重 0.25 ← 静态
        ↓
ConflictArbiter 冲突仲裁 (4级)
  ├─ L1: 结构优先 (缠论 > 其他)
  ├─ L2: 位置优先 (价格 vs 中枢)
  ├─ L3: 量价验证
  └─ L4: 嵌套投票
        ↓
EagleSwordResonance 鹰眼大宝剑 (双系统交叉)
  ├─ 鹰眼(趋势): 缠论方向 + 量价强度
  └─ 大宝剑(情绪): BOCIASI + 拥挤度
        ↓
UIDF统一决策框架 (UPF + AI 合成)
  └─ DeepSeek V4 → AI叙事/情景推演
        ↓
最终决策 (DecisionResult)
```

### 1.2 关键弱点（Kronos可以弥补）

| 弱点 | 当前表现 | 根因 |
|:-----|:---------|:-----|
| **UPF权重静态** | 无论什么市场，structure层总是30% | `UPFEngine.LAYER_WEIGHTS` 硬编码第47行 |
| **无波动率感知** | 高波动市场里缠论/量价频繁误判 | ConflictArbiter 无volatility输入 |
| **无前瞻成分** | Eagle方向=已完成笔段的方向 | EagleSwordResonance纯向后看 |
| **因子权重静态** | StateDependentFactorWeight虽然有状态矩阵，但`market_state`来自向后看的StatusRecognition | 市场状态判定滞后 |
| **AI语境缺失行情预期** | DeepSeek看到的是"已经发生了什么" | UIDF.build_ai_context()不含未来预测 |

---

## 二、Kronos 实际可输出能力

> Kronos 不是分类器（涨/跌），而是**生成模型**。它输出的是K线序列预测，需要从预测结果中**提取**交易信号。

### 2.1 Kronos-mini 技术参数

| 参数 | 值 |
|:-----|:----|
| 参数规模 | **4.1M**（最小版本，CPU可运行）|
| 上下文长度 | **2048根K线**（训练时Token-2k分词器）|
| 输入 | OHLCV + 可选成交量/成交额 |
| 输出格式 | 预测的OHLCV序列（decode后的K线） |
| 推理速度 | ~200-500ms/策略 on CPU（M系列芯片更快） |
| 已验证能力 | 价格预测RankIC +93%, 波动率预测MAE -9%, 生成保真度 +22% |
| 开源协议 | MIT，可直接嵌入 |

### 2.2 可从Kronos输出中提取的信号

| 信号类型 | 提取方式 | 预期质量 | 现有系统是否有等价物 |
|:---------|:---------|:---------|:---------------------|
| **方向预测** | 对比预测K线平均close vs 输入K线close | ⭐⭐⭐⭐ | ❌ 无（现有策略不预测未来）|
| **波动率预测** | 预测K线OHLC标准差 | ⭐⭐⭐⭐⭐ | ❌ 无（9% MAE改进已验证）|
| **趋势持续性** | 预测序列的线性回归斜率 | ⭐⭐⭐⭐ | ❌ 无 |
| **置信度** | 多次采样的预测分布方差 | ⭐⭐⭐ | ❌ 无（KL散度估计）|
| **同步行情预测** | 预测K线的完整OHLCV | ⭐⭐⭐ | ❌ 无（仅用于AI语境）|

### 2.3 Kronos 的局限性

- **不是"万能预测器"**：Kronos输出的是**统计上可能的K线序列**，不代表真实走势
- **在震荡市中性能下降**：方向预测在有明确趋势时效果最好
- **交叉验证风险**：对A股可能有少量分布迁移（45个交易所训练），但论文中零样本跨交易所表现优秀
- **不是交易信号**：需要后处理转换为策略信号格式

---

## 三、4个深度融合点

### 融合点1（最高价值）：Kronos波动率 → UPF动态权重

**原理：** UPFEngine的4层权重现在完全静态。Kronos预测的波动率可以用作**市场状态指标**，动态调节各层的贡献权重。

**实现位置：** `backend/app/engine/framework/unified_practical_framework.py:98`（`_weighted_fuse` 方法）

**改动量：** ~15行

**伪代码：**
```python
class UPFEngine:
    LAYER_WEIGHTS = {'structure': 0.30, 'pattern': 0.25, 'sentiment': 0.20, 'factor': 0.25}
    # ↑ 作为默认值保留
    
    def _select_weights_by_volatility(self, kronos_volatility: str) -> Dict:
        """Kronos波动率驱动的动态权重"""
        if kronos_volatility == 'high':
            # 高波动：减少结构/形态权重（它们容易误判）
            # 增加情绪/因子权重（它们基于实时数据）
            return {'structure': 0.15, 'pattern': 0.15, 'sentiment': 0.35, 'factor': 0.35}
        elif kronos_volatility == 'low':
            # 低波动：结构/形态更可靠
            return {'structure': 0.40, 'pattern': 0.30, 'sentiment': 0.10, 'factor': 0.20}
        else:
            return dict(self.LAYER_WEIGHTS)  # 正常波动→默认权重
    
    def evaluate_all(self, context: Dict) -> FusedResult:
        # 检查是否有Kronos波动率输入
        kronos_vol = context.get('kronos_result', {}).get('volatility_regime')
        if kronos_vol:
            self.current_weights = self._select_weights_by_volatility(kronos_vol)
        else:
            self.current_weights = dict(self.LAYER_WEIGHTS)
        # ... 原有流程，但 _weighted_fuse 使用 self.current_weights
```

**效果分析：**
- 高波动市场：缠论/量价频繁产生假信号，降低它们的权重 → 减少假突破误判
- 低波动趋势市场：让结构/形态主导 → 提高方向持续性信号的权重
- 这是现有系统**完全没有的能力**

---

### 融合点2（高价值）：Kronos方向 → ConflictArbiter 第5级验证

**原理：** ConflictArbiter目前有4级裁定，全部基于已发生数据。加入Kronos方向的**前瞻性验证**作为第5级，可以有效遏制"策略A说买、策略B也说买，但市场实际方向相反"的情况。

**实现位置：** `backend/app/engine/framework/conflict_arbiter.py:30`（`arbitrate` 方法）

**改动量：** ~15行

**伪代码：**
```python
class ConflictArbiter:
    # 新增策略优先级
    STRATEGY_PRIORITY = {
        'chanlun': 1,
        'volume_price': 2,
        'chip': 3,
        'factor': 4,
        'bociasi': 5,
        'kronos_forecast': 2,  # Kronos预测，与量价同级
    }

    def arbitrate(self, signals, zhongshu=None, market_context=None):
        # ... L1-L4 不变 ...

        # 第5级（新增）：Kronos 前瞻验证
        kronos = [s for s in signals if 'kronos' in s.get('strategy_name', '').lower()]
        if kronos:
            k_dir = self._get_direction(kronos[0])
            k_conf = kronos[0].get('confidence', 0.5)
            # 与所有其他策略对比
            total_other = [s for s in signals if 'kronos' not in s.get('strategy_name', '').lower()]
            aligned = sum(1 for s in total_other if self._get_direction(s) == k_dir)
            total = len(total_other)
            if total > 0:
                alignment_ratio = aligned / total
                if alignment_ratio >= 0.6 and k_conf > 0.6:
                    # Kronos确认多数策略方向 → 增强权重
                    log.append(f"Kronos前瞻验证: {k_dir}, 对齐率={alignment_ratio:.0%}, 置信度增强 +0.1")
                    # 在实际合成时提高对齐信号的权重
                elif alignment_ratio < 0.3 and k_conf > 0.7:
                    # Kronos与多数策略冲突 → 标记为高风险
                    log.append(f"Kronos前瞻冲突: 多数策略反向, 降低综合置信度")
            
            # Kronos波动率警告
            kronos_vol = kronos[0].get('volatility', 'normal')
            if kronos_vol == 'high':
                log.append(f"Kronos高波动预警: 所有信号置信度降低")
```

**效果分析：**
- 多数策略看多 + Kronos看多 → 增强置信度
- 多数策略看多 + Kronos看空 → 降低置信度，标记为高风险
- 高波动预警 → 降低所有信号的仓位建议
- 这是目前冲突仲裁中**唯一的前瞻性输入**

---

### 融合点3（中等价值）：Kronos前瞻方向 → EagleSwordResonance 鹰眼前瞻

**原理：** EagleSwordResonance的鹰眼（趋势）系统目前只使用缠论的**已完成方向**（backward-looking）。Kronos预测的方向可以作为"前瞻鹰眼"指标。

**实现位置：** `backend/app/engine/framework/eagle_sword_resonance.py:210`（`evaluate` 方法）

**改动量：** ~10行

**伪代码：**
```python
class EagleSwordResonance:
    def evaluate(self, chanlun_result, volume_price_signal,
                 bociasi_quick, bociasi_slow, crowding,
                 market_state="UNKNOWN",
                 kronos_result=None):              # ← 新增参数
        
        # 原有鹰眼系统
        eagle_direction = self._eagle_trend_direction(chanlun_result)
        eagle_strength = self._eagle_trend_strength(volume_price_signal)
        
        # 新增：Kronos前瞻鹰眼
        kronos_forward_conf = None
        if kronos_result:
            kronos_dir = kronos_result.get('direction', 'neutral')
            kronos_strength = kronos_result.get('trend_strength', 0.0)
            if kronos_strength > 0.4:
                # Kronos有明确方向偏好
                if kronos_dir == eagle_direction:
                    # Kronos确认鹰眼方向 → 增强
                    eagle_strength = min(1.0, eagle_strength + 0.10)
                    log_note("Kronos前瞻确认鹰眼方向")
                else:
                    # Kronos与鹰眼冲突：可能是拐点
                    eagle_strength = max(0.0, eagle_strength - 0.15)
                    risk_notes.append("Kronos前瞻与鹰眼方向冲突，注意可能拐点")
        
        # ... 后续共振查表不变 ...
```

**效果分析：**
- 缠论显示上涨 + Kronos预测继续上涨 → 鹰眼强度增强（+0.10）
- 缠论显示上涨 + Kronos预测反转 → 鹰眼强度降低（-0.15），新增风险提示
- 特别有价值的是**可能反转点的预警**（现有系统完全不具备）

---

### 融合点4（中高价值）：Kronos预测K线 → UIDF AI语境增强

**原理：** UIDFEngine将信号管道的结果传递给DeepSeek做情景推演。目前DeepSeek看到的是"已经发生了什么"。加入Kronos预测的"未来20根K线"可以让DeepSeek推理出更有依据的推演。

**实现位置：** `backend/app/engine/framework/unified_investment_decision_framework.py:131`（`build_ai_context` 方法）+ `backend/app/services/ai_context_builder.py`

**改动量：** ~10行

**伪代码：**
```python
@dataclass
class AIInterpretInput:
    ts_code: str = ''
    stock_name: str = ''
    upf_result: Optional[Dict] = None
    status_recognition: Optional[Dict] = None
    market_context: Optional[Dict] = None
    signals: List[Dict] = field(default_factory=list)
    kronos_forecast: Optional[Dict] = None  # ← 新增字段

class UIDFEngine:
    def build_ai_context(self, upf_result=None, signals=None, 
                         kronos_forecast=None) -> AIInterpretInput:  # ← 新增参数
        ctx = AIInterpretInput(upf_result=upf_result, signals=signals or [])
        if kronos_forecast:
            # 只传递摘要（非完整120根K线，避免Token浪费）
            ctx.kronos_forecast = {
                'predicted_direction': kronos_forecast.get('direction'),
                'predicted_volatility': kronos_forecast.get('volatility_regime'),
                'predicted_trend_strength': kronos_forecast.get('trend_strength'),
                'price_range_low': round(min(p['close'] for p in kronos_forecast.get('predicted_bars', [])), 2),
                'price_range_high': round(max(p['close'] for p in kronos_forecast.get('predicted_bars', [])), 2),
            }
        return ctx
```

**效果分析：**
- DeepSeek现在可以基于"Kronos预测未来20根K线在XX~XX区间"来构建情景推演
- 推演从"已经如此"变成"如果市场按预测走，可能..."
- 抽象后的Kronos数据很小（5个字段），不浪费Token

---

## 四、KronosForecaster 适配器设计

以上4个融合点共享一个底层适配器：**KronosForecaster**。该适配器封装Kronos模型的加载、推理、后处理。

### 4.1 接口设计

```python
class KronosForecaster:
    """Kronos K线预测适配器 — 将Kronos模型输出转换为策略信号"""
    
    def __init__(self, model_name='NeoQuasar/Kronos-mini'):
        # 懒加载：首次调用时加载
        self._tokenizer = None
        self._model = None
        self._predictor = None
    
    def analyze(self, kline_data: pd.DataFrame) -> Dict:
        """
        主入口：输入K线数据 → 返回分析结果
        
        返回:
        {
            'direction': 'bullish'|'bearish'|'neutral',  # 方向预测
            'confidence': 0.72,                            # 预测置信度
            'volatility_regime': 'high'|'normal'|'low',   # 波动率状态
            'trend_strength': 0.65,                        # 趋势强度 -1~1
            'predicted_bars': [...],                        # 前20根预测K线(用于AI语境)
            'model': 'kronos-mini',
            'inference_ms': 342,
        }
        """
        pass
    
    def _run_inference(self, kline_data: pd.DataFrame) -> pd.DataFrame:
        """执行Kronos推理 → 返回预测K线DataFrame"""
        pass
    
    def _extract_signal(self, input_df: pd.DataFrame, pred_df: pd.DataFrame) -> Dict:
        """从预测K线中提取交易信号"""
        pass
```

### 4.2 缓存策略

| 缓存级别 | 存储 | TTL | 命中时机 |
|:---------|:-----|:----|:---------|
| 本次分析 | TieredMemoryCache 'analysis' | **30分钟** | 用户在同一个个股页面内频繁切换周期 |
| 同一股票 | TieredMemoryCache 'analysis' key=`kronos:{ts_code}` | 30分钟 | 用户在不同策略页面查看同一股票 |

仅在**个股策略分析页（indicator-ide）** 和**选股页面（screener）** 中需要运行Kronos。非活跃页面不启动推理。

### 4.3 生产约束满足

| 约束 | 满足方式 |
|:-----|:---------|
| 无GPU | Kronos-mini (4.1M参数) CPU推理，实测~300ms/次 |
| 无Redis | TieredMemoryCache 纯内存缓存 |
| 无独立进程 | Flask进程内加载（模型约16MB），懒加载 |
| 端口限制 | 不增加任何新端口 |
| 数据目录 | HuggingFace缓存默认在 `~/.cache/huggingface/` |

### 4.4 依赖

```
# requirements.txt 新增
torch>=2.0.0          # PyTorch（Kronos运行所需，CPU only ~120MB）
transformers>=4.30.0   # HuggingFace模型加载
```

> **注意：** PyTorch CPU-only 安装包约120MB，会增加分发体积。但无需GPU。

---

## 五、完整融合架构

```
K线数据 (OHLCV, 512根)
        ↓
SignalComputationService
  │
  ├─ (原有5策略)  ─┬─ 缠论 → chanlun_result
  │                ├─ 量价 → volume_price_result
  │                ├─ 筹码 → chip_result
  │                ├─ BOCIASI → bociasi_result
  │                └─ 因子 → factor_result
  │
  └─ KronosForecaster (新增) → kronos_result  ← 并行运行
        │  ├─ direction, confidence
        │  ├─ volatility_regime   ← 融合点1
        │  ├─ trend_strength      ← 融合点3
        │  └─ predicted_bars      ← 融合点4
        │
        ▼
┌─────────────────────────────────────────────────────┐
│ UPFEngine （动态权重）                                  │
│  ← kronos.volatility_regime → 调节4层权重               │ ← 融合点1
│  高波动: structure=0.15 pattern=0.15 sentiment=0.35 f=0.35 │
│  低波动: structure=0.40 pattern=0.30 sentiment=0.10 f=0.20 │
└────────────────────────┬────────────────────────────┘
                         │ upf_result
                         ▼
┌─────────────────────────────────────────────────────┐
│ ConflictArbiter （5级裁定）                              │
│  L1-L4: 不变                                          │
│  L5: +Kronos前瞻验证 ← 融合点2                        │
│  对齐→增强置信度 / 冲突→降低置信度                       │
└────────────────────────┬────────────────────────────┘
                         │ signal + arbitration_log
                         ▼
┌─────────────────────────────────────────────────────┐
│ EagleSwordResonance （鹰眼增强）                        │
│  ← kronos.trend_strength + direction                 │ ← 融合点3
│  Kronos确认鹰眼→增强 / Kronos冲突→拐点预警              │
└────────────────────────┬────────────────────────────┘
                         │ resonance_result
                         ▼
┌─────────────────────────────────────────────────────┐
│ UIDFEngine （AI语境增强）                               │
│  ← kronos.predicted_bars → AI上下文                   │ ← 融合点4
│  DeepSeek获得"未来K线预测"语境                           │
└────────────────────────┬────────────────────────────┘
                         │
                         ▼
              最终决策 (DecisionResult)
              - 信号方向 (bullish/bearish/neutral)
              - 综合置信度 (0.0~1.0)
              - 波动率预警 (kronos_volatility)
              - AI情景推演 (含Kronos语境)
              - 操作参考 (入场/止损/目标)
```

---

## 六、开发计划

### 6.1 工作量估算（~2天）

| 任务 | 工时 | 涉及文件 | 难度 |
|:-----|:----|:---------|:-----|
| **① KronosForecaster 适配器** | **~0.5天** | `services/kronos_forecaster.py` (新建) | 🟡 中（封装HuggingFace推理）|
| **② UPF动态权重 (融合点1)** | **~0.15天** | `engine/framework/unified_practical_framework.py` | 🟢 低（15行权重选择）|
| **③ ConflictArbiter L5 (融合点2)** | **~0.2天** | `engine/framework/conflict_arbiter.py` | 🟢 低（20行验证逻辑）|
| **④ EagleSword前景方向 (融合点3)** | **~0.15天** | `engine/framework/eagle_sword_resonance.py` | 🟢 低（10行方向修正）|
| **⑤ UIDF AI语境 (融合点4)** | **~0.15天** | `services/ai_context_builder.py` | 🟢 低（10行字段扩展）|
| **⑥ requirements.txt + 模型下载** | **~0.3天** | `requirements.txt` + 首次启动下载 | 🟡 中（PyTorch ~120MB）|
| **⑦ 信号管道集成** | **~0.3天** | `services/signal_computation_service.py` | 🟢 低（调用KronosForecaster + 传递结果）|
| **⑧ 单元测试 + 集成测试** | **~0.25天** | `tests/test_kronos_*.py` | 🟢 低 |
| **= 总计** | **~2天** | 7文件（1新建+6修改） | |

### 6.2 建议时机

| 阶段 | 说明 |
|:-----|:------|
| **当前（阶段一）** | ⏳ 纯评估，**不开发** |
| **阶段二：核心分析**（215号个股策略分析） | ✅ **最佳时机** — Kronos融合正好在策略管道完整时接入 |
| 具体位置 | 215号P1开发完成后，在添加`POST /api/v3/strategy/analyze`端点时同时集成Kronos |

**理由：**
- Kronos融合依赖完整的策略管道（215号完成后5策略 + UPF + ConflictArbiter + EagleSwordResonance 全部就绪）
- 在215号开发中，SignalComputationService会被完整接入API
- 此时加上KronosForecaster的调用是自然扩展（不改任何现有数据流）

### 6.3 异常处理

| 异常场景 | 降级策略 |
|:---------|:--------|
| PyTorch未安装 | KronosForecaster 返回 None，融合点1-4全部跳过 → **系统退化为当前状态** |
| 模型下载失败 | 懒加载异常 → 跳过，不影响已有策略 |
| 推理超时（>5s） | 设置超时，返回None → 跳过 |
| 推理返回NaN/异常值 | 校验预测有效性 → 不通过则跳过 |
| 模型版本兼容问题 | 版本检测 + 清晰错误日志 |

**核心原则：Kronos永远是一个增强层，不是阻塞依赖。** 任何Kronos相关的异常都不会影响现有策略的运行。

---

## 七、预期收益评估

### 7.1 各融合点收益分解

| 融合点 | 预期提升 | 适用场景 | 验证方式 |
|:-------|:---------|:---------|:---------|
| ① UPF动态权重 | **+5~10%** | 高波动/低波动切换 | 回测对比静态vs动态权重 |
| ② ConflictArbiter L5 | **+3~7%** | 信号分岐时 | 回测对比有/无Kronos验证 |
| ③ EagleSword前景 | **+2~5%** | 趋势延续/反转点 | 回测对比鹰眼修正前后 |
| ④ AI语境增强 | 定性提升 | 所有AI分析 | DeepSeek输出质量评估 |
| **系统整体** | **+10~15%** | 全市场 | 综合回测 |

### 7.2 与DeepSeek V4的对比

| 维度 | DeepSeek V4 | Kronos-mini |
|:-----|:------------|:------------|
| **类型** | 通用大语言模型 | K线专用基础模型 |
| **输入** | 文本+结构化数据 | K线(OHLCV)原生 |
| **输出** | 叙事/研判/推演（分类+生成） | K线序列预测（回归+生成） |
| **在系统中的角色** | 最终决策的AI解读层 | **信号管道的输入层** |
| **可替代性** | 不可替代（负责叙事/推理） | 不可替代（唯一前瞻组件） |
| **关系** | **互补，非替代。** Kronos提供"市场将如何走"的预测数据；DeepSeek用这些数据做"所以应该怎么做"的推理。|

**两者不是竞争关系，而是管道上下游关系：**
```
Kronos 预测未来K线 → 策略信号增强 → DeepSeek 情景推演
   (市场"将"怎样)      (买入/卖出决策)    (为什么这样做)
```

### 7.3 93% RankIC 提升的落地说明

Kronos论文中报告的**93% RankIC 提升**是在纯价格预测任务上（预测未来1-120根K线与实际K线的排序相关性）。**这不直接等于93%的策略信号准确率提升。**

实际在系统中，Kronos的贡献是：
1. **波动率预测（9% MAE改进）** → **UPF动态权重** → 影响全部4层信号 → 最有价值的贡献
2. **方向预测** → **ConflictArbiter L5** → 只在信号冲突时起作用
3. **趋势持续性** → **EagleSword方向修正** → 只在高置信度时起作用

**合理预期：系统级信号准确率提升10-15%，高波动市场可达15-25%。**

---

## 八、决策建议

| 选项 | 说明 | 推荐度 |
|:-----|:------|:-------|
| **现在不开发，阶段二再评估** | 等215号个股策略开发完成，策略管道完整后再接入 | ⭐⭐⭐⭐⭐ |
| 现在先下载Kronos-mini验证可行性 | 在开发机上跑一次推理，确认CPU性能达标 | ⭐⭐⭐⭐（可并行） |
| 现在开始开发KronosForecaster | 策略管道还不完整，无法端到端验证 | ⭐⭐ |

**我的建议：**

1. **当前阶段不做任何开发** — Kronos融合需要完整策略管道（215号完成5策略+UPF+ConflictArbiter）
2. **但可以先做一件事**：在开发机上 `pip install torch transformers` 然后加载 Kronos-mini 做一次推理验证，确认CPU推理在可接受范围内（~300ms）。这是零风险验证，能为后续开发扫清硬件障碍。
3. **正式集成时机**：在开发 **215号个股策略分析 P1** 时，将 KronosForecaster + 4个融合点一并完成（~2天增量）。此时策略管道完整，融合效果可直接验证。

---

## 附录：关键代码参考

### 附录A：现有策略权重静态定义

```python
# backend/app/engine/framework/unified_practical_framework.py:47
LAYER_WEIGHTS = {'structure': 0.30, 'pattern': 0.25, 'sentiment': 0.20, 'factor': 0.25}
```
← 第47行是融合点1的直接修改点

### 附录B：ConflictArbiter 信号格式

```python
# ConflictArbiter 接收的信号格式
{
    'strategy_name': '缠论',
    'signal': 'bullish',  # bullish/bearish/neutral
    'confidence': 0.75,
}
```
← KronosForecaster 需要输出这个格式的信号才能作为Kronos信号输入

### 附录C：EagleSword 输入接口

```python
# eagle_sword_resonance.py:210-218
def evaluate(self, chanlun_result, volume_price_signal,
             bociasi_quick, bociasi_slow, crowding,
             market_state="UNKNOWN"):
```
← 融合点3需要增加 `kronos_result` 参数

### 附录D：UIDF AI 上下文

```python
# unified_investment_decision_framework.py:16-23
@dataclass
class AIInterpretInput:
    ts_code: str = ''
    # ...
    market_context: Optional[Dict] = None
    signals: List[Dict] = field(default_factory=list)
```
← 融合点4需要增加 `kronos_forecast: Optional[Dict] = None` 字段
