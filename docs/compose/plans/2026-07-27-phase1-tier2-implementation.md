# Phase 1 — 第二梯队实施计划

> **基准文件**：303号《机会图谱实施执行参考与预计算管道方案》§三
> **执行顺序唯一基准**：303号文档

**目标**：完成第二梯队全部 2 项任务（P0.2 + P0.1），产出可独立运行的估值引擎和阶段判定引擎。

**架构**：两个任务相互独立可并行。统一阶段判定引擎整合 5 个现有信号源；估值引擎使用四锚加权合成框架。

**审阅关注点**：
- P0.2：五源融合 ≥3 一致确认 + 涨停交叉校验 + ORM 行业数据走 DataManager 封装
- P0.1：财报空窗期说明（季频数据不变化非故障）+ valuation_level 5档扩展

---

### Task 1: P0.2 统一阶段判定引擎

**文件**：
- Create: `backend/app/opportunity_atlas/__init__.py`
- Create: `backend/app/opportunity_atlas/phase_detector.py`

**产出**：`PhaseDetectionEngine` 类，接收日线/筹码/资金流向数据，产出 `main_force_phase`/`phase_confidence`/`price_position`/`trend_direction`/`fund_flow` 标签。

**接口设计**：
```python
class PhaseDetectionEngine:
    def __init__(self, data_manager=None)
    def compute_tags(self, ts_code: str, df: pd.DataFrame) -> dict
        # 返回 {
        #   'main_force_phase': 'building'|'washing'|'lifting'|'distributing'|'unknown',
        #   'phase_confidence': 0.0-1.0,
        #   'price_position': 'low_zone'|'mid_zone'|'high_zone',
        #   'trend_direction': 'up'|'down'|'sideways',
        #   'fund_flow': '5d_inflow'|'5d_outflow'|'mixed'|'none',
        # }
```

**核心逻辑**：
1. Step 1-价格位置：近120日分位 → price_position
2. Step 2-量能模式：均量对比 + 量价协调性
3. Step 3-资金流向：5日大单净额方向
4. Step 4-筹码确认：ASR 量化阈值 + 筹码主峰位置
5. Step 5-五源投票：5个输入源各自投票 → ≥3一致确认 → 涨停交叉校验

**输入源（复用现有代码逻辑）**：
- `TradingPhaseDetector` → `detect_phase()` 的阶段输出
- `MainForceScorer._score_moneyflow()` → 资金流向评分
- `StageDetector.detect()` → 四阶段判定
- `ChipDistributionEstimator.estimate()` → 筹码分布
- `VolumePriceStrategy` → 趋势方向

---

### Task 2: P0.1 估值引擎（四锚加权合成框架）

**文件**：
- Create: `backend/app/opportunity_atlas/valuation_estimator.py`

**产出**：`ValuationEngine` 类，四锚加权合成，产出估值标签。

**接口设计**：
```python
class ValuationEngine:
    def __init__(self, data_manager=None)
    def compute_tags(self, ts_code: str) -> dict
        # 返回 {
        #   'valuation_level': 'extreme_low'|'low'|'fair'|'high'|'extreme_high',
        #   'valuation_deviation': float,  # -100~+100
        #   'pe_percentile_5y': float,
        #   'pb_percentile_5y': float,
        #   'fcf_yield': float,
        #   'dividend_yield': float,
        #   'fina_health': 'pass'|'suspicious'|'fail',
        #   'roce_pass': bool,
        #   'composite_rating': float,  # -2.0 ~ +2.0
        # }
```

**四锚结构**：
- 资产锚 (PB分位法) — 权重因行业而异
- 收益锚 (PE分位+PEG) — 权重因行业而异
- 现金流锚 (FCF/EV) — 权重因行业而异
- 修正锚 (调整后PE) — 高研发行业权重更大

**行业权重分配**：见表297号§3.1（蓝筹/成长/周期/科技/金融/稳定/微小盘）

**财报空窗期说明**：fina_health 等季频标签不每日变化不是故障

---

## 验证

- [ ] `python -c "from app.opportunity_atlas.phase_detector import PhaseDetectionEngine; print('OK')"`
- [ ] `python -c "from app.opportunity_atlas.valuation_estimator import ValuationEngine; print('OK')"`
- [ ] `ruff check backend/app/opportunity_atlas/`
