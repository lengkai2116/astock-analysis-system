# 480号｜pre_feat structure_ext 恒空修复（474号 _cl 变量遮蔽）

**状态**：✅ 已实施+验证（2026-09-24，提交 待定）
**编号**：480 号（开号于 2026-09-24）
**关联**：479-3 遗留登记⑤（pre_feat 真实重算时暴露）；根因溯源 474 号（commit 4889217，2026-09-22）

## 一、起因
479-3 pre_feat 真实重算时，日志暴露 `RAW结构位置扩展字段失败 [8股]`（data_daemon:3923 except），实测 8/8 股 `structure_ext={}` 恒空。已登记为 479 方案遗留⑤，用户拍板开 480 号修复。

## 二、根因（已确证）
`data_daemon._raw2_one`（`_precompute_raw_features` 单股闭包）内：
- **:3594** `_cl = features.get('chanlun', {})` —— 定义 chanlun dict 引用，供多处使用（:3632/:3648/:3655 `_cl.get(...)`、:3929）。
- **474号（commit 4889217）在 valuation_ext 段 :3829** 把同名 `_cl` 重赋值为 `_bs0.get('current_liab')`（scalar，float 或 None）。
- 该 `_cl` 遮蔽持续到函数尾部，**结构位置扩展段（16段）:3929 `_cl.get('trend_direction','')`** 实为对 scalar 调 `.get` → 抛 `numpy.float64/NoneType object has no attribute 'get'`，被 :3932 except 吞 → `structure_ext={}`。

`structure_ext`（365号 Phase 6 补产出）含 `support_price`/`resistance_price`（支撑阻力，接 `shared_support_resistance` 461-11 唯一 SSOT）+ `indicator_status`（`ma=<ma_alignment>,trend=<trend_direction>`）。恒空导致 dim2 `_assess_vs_indicator`（读 `indicator_status` 的 `ma=`，:571）在 RAW-2 侧喂不到均线排列→ `ma=` 空，dim2 vs_indicator 只能靠 RSI 单源。

**性质**：纯**事实接线（因）**缺陷——数据已有（chanlun dict / ma_alignment），仅因变量名遮蔽未透传。**不触判定逻辑（果）**，符合 445 冻结边界可改。

## 三、修复
仅做**局部变量改名**，消除遮蔽，不动 474 号口径逻辑：
- `data_daemon.py:3829` `_cl = _bs0.get('current_liab')` → `_cur_liab = _bs0.get('current_liab')`（:3830/:3831 同步改名）。

`_cl`（chanlun dict）在 474 段之后不再被重赋，16段 :3929 `_cl.get('trend_direction','')` 恢复读取真实 chanlun dict。

## 四、验证（2026-09-24，daemon 停止态 + compute_cache.db 备份）
- **探针脚本** `backend/scripts/_480_structure_ext_probe.py`（8 股集合，`_precompute_raw_features` 定向重算，前后对比）：
  - **回算前：8/8 `structure_ext` 恒空**（复现 bug）；
  - **回算后：8/8 全部真实落库（ALL_OK）**——
    - 600519 `ma=mixed` support=1170.28 resistance=1285.76；
    - 000002 `ma=bullish` support=3.33 resistance=4.19；
    - 300750 `ma=bearish` support=295.5 resistance=366.91；
    - 002594 `ma=bearish` support=81.9 resistance=89.38；
    - 余 4 只（601318/000001/600036/600276）`ma=mixed`，均带支撑阻力。
  - `trend=` 为空系 461-7 已知事实（`trend_direction` 来源缺、state_label 已换接 chanlun trend 真值），非本 bug 范畴。
- **单元回归**：`test_442_vs_indicator/test_461_dim11/test_461_dim10/test_dim1_gate/test_426` **57 passed**；`test_428_gap_fixes::test_raw2_uses_run_with_timeout` 失败为**预先存在**（stash 至 clean HEAD 同样失败，是源码字符串断言与 RAW-2 当前写法不匹配的陈旧测试，与本改动无关）。
- daemon 已恢复运行 + compute_cache.db 备份 `.bak_480_*`。

## 五、遗留观察
- `structure_ext.indicator_status` 的 `trend=` 仍空（461-7 已知：`trend_direction` 无生产源，`state_label`/`trend_alignment` 已改接真值）；dim2 `_assess_vs_indicator` 主读 `ma=`（已真实），`trend=` 非必需。是否补 `trend=` 真值（如透传 chanlun tre direction）属后续观察项，不在本号处理。
