# Phase 1 — 第一梯队实施计划

> **基准文件**：303号《机会图谱实施执行参考与预计算管道方案》§三（唯一基准）
> **执行顺序唯一基准**：303号文档，本文档是其实施分解

**目标**：完成第一梯队全部 4 项任务，产出可运行的引擎代码、因子注册和 Treemap 前端原型。

**架构**：四个任务互相独立、可并行；P0.6 同时修复 Red Line 5 ORM 直读问题。

**Tech Stack**：Python 3.10+、Flask、pandas、ECharts 5.x

---

## 任务分解

### Task 1: P0.5 MarketSentimentService 改造

**文件**：
- Modify: `backend/app/services/market_sentiment_service.py`
- Test: `backend/tests/test_sentiment_service.py`

**产出**：改造后的 `get_sentiment_phase()` 返回 `ice/recovery/climax/ebb` 四态，新增炸板率日频近似值 `_estimate_daily_sealing_rate()`。

**审阅关注点**：
- 阶段名 `high` → `climax` 对齐标签体系
- 新增 `neutral` ↔ `ebb` 区分阈值（炸板率 > 60% + 连板空间龙头断板 → ebb）
- BOCIASI 保留为辅助确认通道

**步骤**：

- [ ] 修改 `market_sentiment_service.py`：
  1. 将 `'high'` 全部替换为 `'climax'`，标签文字 `'情绪高潮'`
  2. 新增 `_estimate_daily_sealing_rate(df)` 方法（基于 daily_cache 的日频封板率近似值）
  3. 修改四阶段映射逻辑：
     - ice: 涨停 < 20 + 最高连板 < 3 + （新增）封板率 < 40%
     - recovery: 涨停 ≥ 20 + 最高连板 ≥ 3 + （新增）非 ebb 条件
     - climax: 涨停 > 80 + 封板率 > 75%（原条件不变，仅改名）
     - ebb: （新增）最高连板 ≥ 3 + 封板率 < 50% → 或炸板率 > 60% + 涨停 < 40
     - 去掉 neutral：不匹配以上任一条件的，如果涨停 > 40 归为 recovery，否则归为 ice
  4. 确保 `get_sentiment_context()` 兼容 snapshot 调用

- [ ] 编写测试 `test_sentiment_service.py`：验证各阶段判定边界条件

- [ ] 运行 `make test` 确认通过

### Task 2: P0.6 SectorRotation 重写 + ORM 整改

**文件**：
- Rewrite: `backend/app/engine/framework/sector_rotation_model.py`
- Modify: `backend/app/data/__init__.py` (DataManager 新增 `get_stock_industry_batch`)
- Test: `backend/tests/test_sector_rotation.py`

**产出**：`SectorRotationModel.evaluate()` 基于缠中说禅板块强弱指标法，产出 `sector_heat` 标签。

**审阅关注点**：
- 重写方法：按行业分组 → 统计各股 MA5>MA20 比率 → 排序 → top_10/top_20/normal/none
- **必须同步实现**：`DataManager.get_stock_industry()` / `get_stock_industry_batch()`

**步骤**：

- [ ] 在 `backend/app/data/__init__.py` DataManager 中新增：
  ```python
  def get_stock_industry(self, ts_code: str) -> str | None:
      from app.models.stock import Stock
      stock = self.session.query(Stock).filter(Stock.ts_code == ts_code).first()
      return stock.industry if stock else None

  def get_stock_industry_batch(self, ts_codes: list[str]) -> dict[str, str | None]:
      from app.models.stock import Stock
      stocks = self.session.query(Stock.ts_code, Stock.industry).filter(
          Stock.ts_code.in_(ts_codes)
      ).all()
      return {s.ts_code: s.industry for s in stocks}
  ```

- [ ] 重写 `sector_rotation_model.py`：
  - 删除原 `get_sector_data()`/`calc_sector_strength()`/`evaluate()` 全部逻辑
  - 新架构：`evaluate_all()` 接收全市场 DataFrame，按行业分组计算强弱值
  - 新方法：`get_sector_heat(ts_code)` 返回 `top_10/top_20/normal/none`
  - 使用 `dm.get_stock_industry_batch()` 获取行业数据

- [ ] 编写测试验证：模拟 3 个行业各 10 只股票，验证板块排序逻辑

### Task 3: P0.3 FactorRegistry 新增 9 因子

**文件**：
- Create: `backend/app/factors/builtin/opportunity.py`（新建文件，包含全部 9 个因子类）
- No changes to `registry.py` 或 `builtin/__init__.py`（自动注册机制已存在）

**产出**：9 个新因子自动注册到 FactorRegistry

**审阅关注点**：
- `required_columns` 对于估值类因子需调整为 `["pe", "pb", "ps"]`（非 OHLCV 数据）
- EMOTION_EXTREME 依赖 BOCIASI 数据，标记为暂缺

**步骤**：

- [ ] 新建 `backend/app/factors/builtin/opportunity.py`，包含：

  1. `PE_PERCENTILE_5Y` — category="valuation", 数据: daily_basic.pe_ttm, 需 5 年历史百分位
  2. `PB_PERCENTILE_5Y` — category="valuation", 数据: daily_basic.pb
  3. `PS_PERCENTILE_5Y` — category="valuation", 数据: daily_basic.ps
  4. `DIVIDEND_YIELD` — category="valuation", 数据: 分红数据（暂返回 NaN，标记 TODO）
  5. `ROE` — category="quality", 数据: fina_indicator.roe
  6. `DEBT_RATIO` — category="quality", 数据: fina_indicator（资产负债率）
  7. `REVENUE_GROWTH` — category="quality", 数据: income（营收增长率）
  8. `PROFIT_GROWTH` — category="quality", 数据: income（净利润增长率）
  9. `EMOTION_EXTREME` — category="emotion", 数据: BOCIASI（暂返回 NaN，标记 TODO）

  每个因子继承 `BaseFactor`，设置正确的 `category`/`subcategory`/`source`/`required_columns`。

- [ ] 验证：启动 Python 导入，确认 9 个因子自动注册

  ```bash
  python -c "from app.factors.registry import get_factor_registry; r=get_factor_registry(); print(r.list_factors(category='valuation')); print(r.list_factors(category='quality'))"
  ```

### Task 4: P1.3 Treemap 前端 ECharts

**文件**：
- Modify: `_ui-prototype/opportunity-treemap.html`

**产出**：三种地图模式（市场/机会/价值）+ 标签筛选栏 + 悬停浮窗 + 预设场景 + fallback 角标

**审阅关注点**：
- 机会地图 fallback：后端返回 `signal_strength_fallback: true` 时，前端标题栏显示 "⚠ 信号强度 Fallback" 角标
- 三种地图各自有不同的浮窗内容
- 使用 ECharts 5.x Treemap

**步骤**：

- [ ] 改造 `opportunity-treemap.html`：
  1. 确保三种地图模式切换（右上角按钮，ECharts 300ms 动画过渡）
  2. 市场地图：外层=行业，大小=流通市值，颜色=涨跌幅
  3. 机会地图：外层=行业，大小=signal_strength（fallback 处理），颜色=持有周期
  4. 价值地图：外层=行业，大小=前收盘价，颜色=估值偏离度
  5. 每种地图的悬停浮窗内容完全不同
  6. 标签筛选栏（15 个常驻 + 6 个折叠）
  7. 预设场景按钮
  8. Fallback 角标逻辑

---

## 验证

- [ ] 每项任务完成后运行 `make test`（或对应 pytest）
- [ ] 启动 Flask 确认无 import 错误
- [ ] 打开 `opportunity-treemap.html` 确认三种地图展示正常
