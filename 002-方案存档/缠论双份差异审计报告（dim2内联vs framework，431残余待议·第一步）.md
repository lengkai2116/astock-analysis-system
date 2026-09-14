---
title: 缠论双份差异审计报告（dim2 内联 vs framework）
type: 审计报告（431 残余待议·第一步产物，为 434 号回迁增量依据）
date: 2026-09-14
version: v1.0
status: 📋 已存档（第一步落地；第二步另开 434 号引用本报告）
related:
  - 431-430号遗留项核查清单与处置建议
  - 411-维度引擎统一实施计划（407-410整合）
  - 412-支撑阻力计算方案（B1 v3.0）
  - 433-IC权重月度滚动重估作业（写侧链路）
---

# 缠论双份差异审计报告（dim2 内联 vs framework）

> **性质**：只读审计（含第一步代码改动记录）。431 残余待议「dim2 `chanlun_config`/`chanlun_strategy` 双份收敛」的第一步交付物——把双份差异**逐类定性**（等价/修复/增强/重命名/dim2 私有优化），为第二步（434 号，方案 A＝framework 权威 + dim2 回归 dim-import-framework）提供**回迁增量清单**与行为变更依据。
>
> **对象**：`dim2_structure_engine.py` 内联 4 区块 vs `app/engine/framework/` 对应文件。
> **手段**：python difflib 符号级 + 行级 diff（`backend/scripts/_audit_dim2_chanlun_diff.py`，产物 `/tmp/chanlun_audit/*.txt`）。

## 一、区块边界（编辑后行号）

| 区块 | dim2 行区间 | framework 对应文件 | 状态 |
|------|------------|-------------------|------|
| chanlun_config.py | :29-:146 | `framework/chanlun_config.py`（118 行） | 双份均 live |
| chanlun_level_validator.py | :147-:409 | ~~`framework/chanlun_level_validator.py`~~ | **framework 份已删（2026-09-14），dim2 份唯一权威** |
| trend_structure_detector.py | :410-:500 | `framework/trend_structure_detector.py`（104 行） | 双份均 live |
| chanlun_strategy.py | :501-:3819 | `framework/chanlun_strategy.py`（3275 行） | 双份均 live |

## 二、diff 总览

| 区块 | dim2 行数 | framework 行数 | 相似度 | 独有行（dim2 / fw） |
|------|:--:|:--:|:--:|:--:|
| chanlun_config.py | 117 | 118 | 92.4%（109/118） | —（头部 + BiConfig 差异） |
| trend_structure_detector.py | 90 | 104 | 81.7%（85/104） | —（头部 + return 结构差异） |
| chanlun_strategy.py | 3318 | 3275 | 95.8%（3179/3318） | **136 / 93**（SequenceMatcher） |
| level_validator | 262 | — | — | dim2 独有（fw 已删） |

> **对 431 §018 交接口径的修正**：原记「dim2 独有 116 行 / framework 独有 80 行、相似度 ~87%」——本报告用 `SequenceMatcher(autojunk=False)` 复测为 **136/93、95.8%**（差异来自 diff 算法与区块提取边界，结论方向一致：**双向分叉、非单向前置**，详见 §四）。

## 三、逐类差异定性

### 3.1 chanlun_config.py（dim2 117 行 vs fw 118 行）

| # | 差异 | 方向 | 定性 |
|---|------|------|------|
| C1 | 模块 docstring + `from dataclasses import dataclass, field` 头部 | fw 有、dim2 无 | **等价**（内联所致：dim2 头部已有 `from dataclasses import dataclass, field`，见 dim2 :17） |
| C2 | **`BiConfig` 少 `@dataclass` 装饰器** | dim2 为普通类、fw 为 dataclass | **行为差异**（431 §018 已知）：dim2 份 `BiConfig()` 不可变默认值共享（类属性），fw 份 dataclass 生成 `__init__`/`__eq__`/`__repr__`；字段默认值一致，实例化用法相同 ⇒ **低危**，但第二步须统一（推荐 fw 的 `@dataclass` 为权威） |
| C3 | 尾部空行 | 差异 | 等价 |

其余 6 个配置类（SegmentConfig / ZhongshuConfig / DivergenceConfig / BuySellConfig / MultiLevelConfig / ChanlunConfig）**逐字节相同**（与 431 §018 一致）。

### 3.2 chanlun_level_validator.py（dim2 262 行）

framework 份已于 2026-09-14 删除（零 live 消费方）。**dim2 内联份为唯一权威**（较新版：多级别重采样 amount 列可选、月度 `'ME'` 取代已废弃 `'M'` 等 23 行差异）——第二步回迁 framework 时**以此为源，勿丢修复**。

### 3.3 trend_structure_detector.py（dim2 90 行 vs fw 104 行）

| # | 差异 | 方向 | 定性 |
|---|------|------|------|
| T1 | 模块 docstring + `import numpy/pandas` 头部 | fw 有、dim2 无 | **等价**（内联所致） |
| T2 | **`detect()` 返回 dict 增加 `assumption1/2/3` 键**（`trend_break`/`higher_low`/`breakout_high`） | **dim2 独有** | **dim2 增强**（123 法则三假设明细输出，供消费方排查）——**回迁增量** |
| T3 | 尾部空行 | 差异 | 等价 |

### 3.4 chanlun_strategy.py（dim2 3318 行 vs fw 3275 行；核心区块）

符号级：dim2 **27** 符号 ⊇ fw **25** 符号（dim2 独有 `_load_precomputed_macd` / `calc_support_resistance`，与 431 F2 一致）。但**函数体层面双向分叉**：

#### A 类｜dim2 独有（framework 缺，**回迁增量**）

| # | 差异 | 定性 | 说明 |
|---|------|------|------|
| A1 | `_MACD_PRECOMPUTED_CACHE` + `_load_precomputed_macd(ts_code)`（:505-:533） | **411 号 Phase 5 预计算 MACD** | 从 `indicator_macd` 预计算表读 DIF/DEA/HIST 数组（DataManager 缓存），供 `calc_macd` 优先使用；fw 无此函数 |
| A2 | `calc_macd(closes, precomputed=None)` 签名扩展（fw 仅 `calc_macd(closes)`） | **411 号 Phase 5 增强** | precomputed 长度匹配则直接返回，否则 raw 计算 fallback；`_calc_stroke_*` 系列 7 处改传 `self._precomputed` |
| A3 | `DivergenceDetector.__init__` 增 `self._precomputed`、`detect()` 增 `precomputed` 参数 | **411 号 Phase 5 增强** | 透传预计算 MACD 到背驰检测 |
| A4 | `ChanlunAnalyzer.analyze()` 第 7 步（:2712-:2718）：从 df 读 `ts_code` → `_load_precomputed_macd` → 传 `precomputed` | **411 号 Phase 5 增强** | fw 对应处直接 `closes=...` |
| A5 | `calc_support_resistance(df, indicator_ma_df)`（:3757-:3808） | **412 号 B1 v3.0 支撑阻力内联** | MA20/MA60 优先从 data_context 的 `indicator_ma_df` 读、raw fallback；**注意与 `shared_support_resistance.py`（`calc_support_resistance(df)` 单参）签名不同**——dim2 内联版为增强版，消费方 `Dim2StructureEngine.evaluate`（:3852）传 `indicator_ma_df` |
| A6 | `fractal_threshold_pct` 默认值 **0 → 0.5**（fw `0`=关闭对齐 czsc；dim2 `0.5`=F-15 规格） | **dim2 修复/规格化** | `ChanlunAnalyzer.__init__`（:2100）+ `WINDOW_CONFIG`（:2152）两处一致；**行为差异**（分形确认阈值收紧） |
| A7 | `StrokeBuilder` 一处尾部 `return False` 死代码删除（fw 有、dim2 无） | **等价清理** | fw `_is_valid_stroke` if/else 均已 return，尾部 `return False` 不可达 |

#### B 类｜framework 独有（dim2 缺；dim2 回归 framework 时**自动获得**）

| # | 差异 | 定性 | 说明 |
|---|------|------|------|
| B1 | **`DivergenceDetector.detect()` 背驰检测主逻辑**（fw :1256-:1293 完整：`_detect_trend_divergence` → `_detect_trend_backtesting` → `_detect_consolidation_divergence` → `_detect_zhongshu_divergence` + 力度法 `_check_strength_method`/`dual_confirmed`/置信度 ×1.3） | **dim2 缺失（严重）** | dim2 版 detect()（:1788-:1792）**只剩 `if len(strokes) < 4: return None` + 3 行字段赋值，无 return 语句 ⇒ 恒返回 None**！`_detect_trend_*` 等方法在 dim2 **仍存在（死代码）**但**无任何调用点**（grep 证实）——**dim2 内联版背驰检测整体失效**。**根因推断**：411 Phase 5 改造时把 `detect()` 主体替换成预计算赋值，误删了背驰调用链。**修复路径**：dim2 回归 framework 后自动恢复（framework 版完整） |
| B2 | `BuySellPointDetector.find()` 的 `only_last` 快速模式参数（fw :1739 签名含 `only_last=False` + :1756-:1777 快速分支 + 342 号修复） | **dim2 删除** | dim2 find() 签名无 `only_last`（:1739 对应处为 3 参）；快速模式（只算最后 K 线买卖点 + 342 号 direction 语义修正）在 dim2 缺失 |
| B3 | `ChanlunAnalyzer.__init__` 的 `only_judge_last` 配置读取（fw :2077-:2080） | **dim2 删除** | 配合 B2：dim2 无快速模式配置 |
| B4 | `analyze()` 第 8 步传 `only_last=self.only_judge_last`（fw :2243） | **dim2 删除** | 配合 B2/B3 |

#### C 类｜双向共有但内部结构差异

| # | 差异 | 定性 |
|---|------|------|
| D1 | 头部 docstring / import 块（fw 有、dim2 内联复用模块级 import） | 等价（内联所致） |
| D2 | `from dataclasses import dataclass, field` 中部 import（dim2 :2926 有 `field`、fw :2426 无） | 等价（内联合并所致） |

## 四、关键结论（翻转 431 F2「dim2 为超集」的函数体层面判断）

1. **符号层**：dim2 27 ⊇ fw 25，dim2 确为**符号超集**（多 `_load_precomputed_macd`/`calc_support_resistance`）。
2. **函数体层**：**双向分叉，且 dim2 存在严重缺陷**——`DivergenceDetector.detect()` 背驰检测主逻辑整体丢失（恒 None），`_detect_trend_*`/`_check_strength_method` 成死代码；`only_last` 快速模式 + `only_judge_last` 配置被删除。**这些都不是「较新修复」，而是 411 改造时的功能退化**。
3. **方案 A（framework 权威 + dim2 回归 dim-import-framework）得到强化**：dim2 删 4 区块改 import framework 后，**背驰检测自动恢复**（B1）+ 快速模式回归（B2/B3/B4）+ BiConfig 统一 `@dataclass`（C2）——均为**修复向**行为变更，非破坏；同时 dim2 独有增量（A1-A6 + T2 + level_validator 新版）须**回迁 framework** 保住。
4. **第二步（434 号）回迁增量清单**（framework 侧新增）：
   - `_load_precomputed_macd` + `_MACD_PRECOMPUTED_CACHE`（A1）
   - `calc_macd(closes, precomputed=None)` 签名扩展 + 7 处 `_calc_stroke_*` 传参（A2）
   - `DivergenceDetector.__init__`/`detect()` precomputed 参数（A3）+ `analyze()` 第 7 步预计算接线（A4）
   - `calc_support_resistance(df, indicator_ma_df)`（A5，注意与 shared 版签名对齐决策）
   - `fractal_threshold_pct` 默认 0.5（A6）
   - `TrendStructureDetector.detect()` return 增 `assumption1/2/3`（T2）
   - `chanlun_level_validator.py` 重建（dim2 内联份为源）
   - `StrokeBuilder` 死代码清理（A7，可选顺带）
5. **第二步删除侧**：dim2 删 4 内联区块（~3800 行）改模块级 import（含 `ChanlunAnalyzer`/`ChanlunScorer`/`ChanlunAlphaModel`/`SignalFusion`/`StrategyValidationLayer`/`ChanlunTheoremValidator`/`ZhongshuFactorSwitch`/config 类/`TrendStructureDetector`/`calc_support_resistance` 等）。

## 五、第一步落地记录（本报告配套）

| # | 动作 | 结果 |
|---|------|------|
| 1 | **消除 F4 混用**：`ChanlunLevelValidator._analyze_level`（dim2 :268-:270）删除 `from app.engine.framework.chanlun_strategy import ChanlunAnalyzer, ChanlunScorer` 动态 import，改用模块级内联版 | 3 行改动；dim2 内部全部消费内联版（唯一实现），不再双份混用 |
| 2 | 差异审计脚本 `backend/scripts/_audit_dim2_chanlun_diff.py` | 可复现；产物 `/tmp/chanlun_audit/*.txt` |
| 3 | 验证 | 见 §六 |

## 六、验证证据（第一步）

| 项 | 证据 |
|---|---|
| py_compile | `dim2_structure_engine.py` → **OK** |
| ruff | `dim2_structure_engine.py` → **`All checks passed!`** |
| 回归（dim2） | `tests/test_396_dim2_engine.py` → **13 passed**（含 `ChanlunLevelValidator`/`BuySellPointDetector`/`calc_support_resistance`） |
| 回归（缠论合成子集） | `tests/test_chanlun_verification.py` 合成子集（12 项，跳过 DB/集成类）→ **12 passed** |
| git 状态 | 受控改动＝`M backend/app/opportunity_atlas/dimensions/dim2_structure_engine.py`（1 行净删）+ `?? backend/scripts/_audit_dim2_chanlun_diff.py`；**未混入用户自有未提交改动** |

> **注意**：`_analyze_level` 改用内联版后，其背驰检测随内联版缺陷（§四-2）**一并失效**（切换前动态 import framework 版是完整背驰）——这是第一步消除混用的**已知副作用**，第二步（434 号 dim2 回归 framework）后自动恢复。若用户在第一步与第二步之间需要 `_analyze_level` 背驰能力，可临时保留 fw import（违背消除混用目标），**不建议**。

## 七、登记

- 431 §019 残余待议更新为「**第一步已落地**」（本报告 §三/§四/§五）；第二步另开 **434 号**（执行计划不变）。
- **434 号已全量完成（2026-09-14 v1.2）**：本报告的回迁增量清单（§四-4）已全部落地——framework 回迁（`_load_precomputed_macd`/`calc_macd(precomputed)`/`DivergenceDetector precomputed`/`fractal_threshold_pct=0.5`/`assumption1/2/3`/level_validator 重建）、shared 支撑阻力合并（`indicator_ma_df` 可选参数）、dim2 删 4 内联区块（4000→258 行）改 import framework + shared；431 §019 残余待议 → **✅ 闭环**。
- `001-沟通记录/2026-09-14.md` §10 ＋ 沟通索引。
- `001-目录索引.md` 431 行尾句更新。
