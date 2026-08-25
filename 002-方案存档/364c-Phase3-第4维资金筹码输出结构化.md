---
title: Phase 3 - 第4维资金筹码输出结构化
type: 实施方案（子方案）
date: 2026-08-21
version: v1.0
parent: 364-七维现状描述系统实施方案（总纲）
---

# 364c - Phase 3：第4维资金筹码输出结构化（10h）

> 目标：将资金筹码维度从简单的state/light二元输出升级为六子维度结构化输出（主力行为阶段、资金流向强度、成本分布结构、筹码信号状态、散户机构博弈、融资杠杆变化），含MainForceScorer.get_sub_scores()新增方法、fund_flow_strength 5级分层、chip_transfer筹码转移检测、control_degree控盘度计算。

---

## 一、当前代码状态

### 1.1 MainForceScorer 当前实现（chip_strategy.py:379-1133）

```python
# 当前架构（逐行）：
# L379-403: MainForceScorer类定义，__init__含_dm/_chip_indicators/_chip_bins
# L412-452: score() — 综合评分0-10，调用6个子评分方法
# L454-518: _score_moneyflow() — A维度：资金流向(0-3分)
#   L483-488: 5日累积大单净额净比率 → flow_score(0-1.0)
#   L491-498: 大单成交占比 → ratio_score(0-0.5)
#   L500-516: 资金连续性 → continuity(0-1.0) + net_days_score(0-0.5)
# L522-572: _score_volume_price() — B维度：价量主力信号(0-3分)
#   L549-551: 拉升阶段（多头+放量）
#   L553-557: 建仓阶段（低位价平量增）
#   L559-563: 洗盘后期（价跌缩量）
#   L565-569: 出货嫌疑（高位放量）
# L574-616: _score_concentration() — C维度：筹码集中度(0-2分)
#   L588-601: 股东户数变化（优先）
#   L605-616: OHLCV稳定性（回退）
# L618-685: _score_retail_contrarian() — D维度：散户反向指标(0-2分)
#   L641-651: 散户5日累积净额占比
#   L653-664: 散户高位买/低位卖判定
#   L666-681: 融资融券反向信号
# L688-807: _score_lhb() + _detect_fake_institution() — E维度：龙虎榜(-0.5~+1.0分)
# L809-878: _score_chip_distribution() — F维度：筹码分布(0-1.5分)
#   L838-844: ASR评估
#   L847-857: SSRP偏离评估
#   L859-866: CYQKL穿越评估
#   L868-874: 筹码峰检测
# L880-934: _calc_main_force_cost() — 主力集中价计算
# L936-1066: identify_phase() — 主力操盘阶段识别
# L1101-1132: get_tags() — 返回主力资金标签
```

**问题**：
- 无`get_sub_scores()`方法：score()返回总分，不暴露各子维度分值
- 无法为第4维的6个子维度提供独立评分
- fund_flow_strength无5级分层标准
- 缺少chip_transfer筹码转移检测
- 缺少control_degree控盘度计算

### 1.2 PhaseDetectionEngine 当前实现（phase_detector.py:29-106）

```python
# 当前架构：
# L29: class PhaseDetectionEngine(DataAwareMixin)
# L42-106: compute_tags() — 主入口
#   L76-79: price_pos + ma_alignment + trend_dir + fund_flow 基础标签
#   L83-94: 8维度阶段向量（chip/fund/stage/asr/trend/ssrp/chan，缺dim_7控盘度）
#   L97: _consensus(dims, extra_tags) → 加权共识
#   L100: _limit_up_cross_check() → 涨停交叉校验
#   L102-106: 输出main_force_phase + confidence + conflict + vote_ratio
```

**当前输出结构**：
```python
{
    'main_force_phase': str,      # building/washing/lifting/distributing/unknown
    'phase_confidence': float,    # 0-1
    'price_position': str,        # low_zone/mid_zone/high_zone
    'trend_alignment': str,       # up_aligned/down_aligned/no_trend
    'fund_flow': str,             # 5d_inflow/5d_outflow/mixed/none
    'phase_conflict': bool,
    'phase_vote_ratio': str,      # JSON字符串
}
```

**问题**：
- 缺少子维度分值暴露（无法为第4维结构化输出提供数据）
- 控盘度维度（维度7）缺失

### 1.3 status_engine中chip_fund维度的当前输出（status_engine.py:254-263）

```python
# L254-263: chip_fund维度
if chip:
    cst = str((chip.get('status_recognition') or {}).get('state', ''))
    put('chip_fund', '流入' if ('拉升' in cst or '建仓' in cst)
        else ('流出' if '出货' in cst else '中性'),
        chip.get('confidence', 0.5),
        [str(e) for e in (chip.get('evidence') or [])[:3]])
else:
    ff = str(tags.get('fund_flow', ''))
    put('chip_fund', '流入' if ff == '5d_inflow' else ('流出' if ff == '5d_outflow' else '中性'),
        0.5, [f'fund_flow={ff}'] if ff else ['筹码/资金数据缺失'])
```

**问题**：
- chip_fund维度仅有state（流入/中性/流出），无6子维度拆解
- evidence仅有3条粗略标签
- 无MainForceScorer各子维度分值

### 1.4 build_seven_dim_report()中fund_chip段落（status_engine.py:638-639）

```python
# L638-639: fund_chip段落
'seg': _seg('资金与筹码状态', dims.get('chip_fund', {}).get('light', 'yellow'),
            f"筹码资金：{dims.get('chip_fund', {}).get('state', '中性')}",
            '谁在买、筹码状态'),
```

**问题**：
- text仅为"筹码资金：{state}"，无主力阶段/资金流向/成本结构等子维度信息
- plain为硬编码

---

## 二、修订内容

### 2.1 新增方法：MainForceScorer.get_sub_scores()

**修改文件**：`backend/app/engine/framework/chip_strategy.py`

**新增位置**：MainForceScorer类内部（L452之后）

```python
def get_sub_scores(self, data: pd.DataFrame, symbol: str = None) -> dict:
    """返回各子维度独立评分（364c Phase 3：供第4维结构化输出使用）

    与score()共享计算逻辑，但额外暴露各子维度分值。

    Returns:
        {
            'total': float,           # 总分0-10
            'moneyflow': float,       # A: 资金流向 0-3
            'volume_price': float,    # B: 价量信号 0-3
            'concentration': float,   # C: 筹码集中度 0-2
            'retail_contrarian': float,# D: 散户反向 0-2
            'lhb': float,            # E: 龙虎榜 -0.5~1.0
            'chip_distribution': float,# F: 筹码分布 0-1.5
            'sub_details': {          # 各子维度详情
                'moneyflow': {
                    'flow_score': float,
                    'ratio_score': float,
                    'continuity': float,
                    'net_days_score': float,
                    '5d_net_lg': float,
                    'positive_ratio': float,
                },
                'concentration': {
                    'holder_change': float|None,
                    'asr': float|None,
                },
                ...
            }
        }
    """
    if data.empty or len(data) < 60:
        return {'total': 0.0, 'moneyflow': 0.0, 'volume_price': 0.0,
                'concentration': 0.0, 'retail_contrarian': 0.0,
                'lhb': 0.0, 'chip_distribution': 0.0, 'sub_details': {}}

    try:
        closes = data['close'].values
        volumes = data['vol'].values if 'vol' in data.columns else (
            data['amount'].values if 'amount' in data.columns
            else np.ones(len(data))
        )
        price_high = np.max(closes[-120:])
        price_low = np.min(closes[-120:])
        price_range = price_high - price_low if price_high > price_low else 1.0
        price_position = (closes[-1] - price_low) / price_range

        score_a = self._score_moneyflow(symbol)
        score_b = self._score_volume_price(closes, volumes, price_position)
        score_c = self._score_concentration(symbol, closes, price_position)
        score_d = self._score_retail_contrarian(symbol, price_position)
        score_e = self._score_lhb(symbol, data)
        score_f = self._score_chip_distribution(symbol, data)

        total = score_a + score_b + score_c + score_d + score_e + score_f

        # 子维度详情
        sub_details = self._build_sub_details(symbol, data, closes, volumes, price_position)

        return {
            'total': round(min(10.0, max(0.0, total)), 2),
            'moneyflow': round(score_a, 2),
            'volume_price': round(score_b, 2),
            'concentration': round(score_c, 2),
            'retail_contrarian': round(score_d, 2),
            'lhb': round(score_e, 2),
            'chip_distribution': round(score_f, 2),
            'sub_details': sub_details,
        }
    except Exception as e:
        logger.error(f"get_sub_scores失败 {symbol}: {e}")
        return {'total': 0.0, 'moneyflow': 0.0, 'volume_price': 0.0,
                'concentration': 0.0, 'retail_contrarian': 0.0,
                'lhb': 0.0, 'chip_distribution': 0.0, 'sub_details': {}}
```

### 2.2 新增方法：MainForceScorer._build_sub_details()

**修改文件**：`backend/app/engine/framework/chip_strategy.py`

```python
def _build_sub_details(self, symbol, data, closes, volumes, price_position) -> dict:
    """构建各子维度详情数据"""
    details = {}

    # A: 资金流向详情
    if symbol:
        try:
            end_str = datetime.now().strftime('%Y-%m-%d')
            start_str = (datetime.now() - timedelta(days=10)).strftime('%Y-%m-%d')
            mf_df = self.dm.get_cached_moneyflow(symbol, start_date=start_str, end_date=end_str)
            if mf_df.empty:
                mf_df = self.dm.get_cached_moneyflow(symbol)
            if not mf_df.empty:
                mf_5 = mf_df.tail(5)
                net_lg_5d = float(mf_5['net_lg_amount'].sum())
                pos_days = int((mf_5['net_lg_amount'] > 0).sum())
                details['moneyflow'] = {
                    '5d_net_lg': round(net_lg_5d / 1e4, 2),  # 万元
                    'positive_days': pos_days,
                    'positive_ratio': round(pos_days / max(len(mf_5), 1), 2),
                }
        except Exception:
            details['moneyflow'] = {}

    # C: 筹码集中度详情
    if symbol:
        try:
            holder_df = self.dm.get_cached_stk_holder(symbol)
            if not holder_df.empty and 'holder_number' in holder_df.columns:
                h = holder_df.dropna(subset=['holder_number']).sort_values('end_date')
                if len(h) >= 2:
                    change = (float(h['holder_number'].iloc[-1]) - float(h['holder_number'].iloc[0])) / float(h['holder_number'].iloc[0])
                    details['concentration'] = {
                        'holder_change_pct': round(change * 100, 2),
                    }
        except Exception:
            pass

    # ASR从筹码分布获取
    if self._chip_indicators:
        details.setdefault('chip_indicators', {
            'asr': self._chip_indicators.get('asr') or self._chip_indicators.get('ASR'),
            'ssrp': self._chip_indicators.get('ssrp') or self._chip_indicators.get('SSRP'),
            'cyqkl': self._chip_indicators.get('cyqkl') or self._chip_indicators.get('CYQKL'),
            'concentration': self._chip_indicators.get('concentration'),
        })

    return details
```

### 2.3 新增方法：MainForceScorer.get_fund_flow_strength()

**修改文件**：`backend/app/engine/framework/chip_strategy.py`

```python
def get_fund_flow_strength(self, symbol: str) -> dict:
    """资金流向5级强度分层（364c Phase 3：对应359号§4.4子维度2）

    5级分层标准（基于359号§4.4）：
      极强：超大单连续3日+净流入>1亿/日
      强：大单+超大单5日净流入，占比>40%
      中等：大单净流入但不连续（positive_ratio<0.6）
      弱：大单流入流出交替（positive_ratio≈0.5）
      极弱/无：5日净额绝对值<阈值

    Returns:
        {'level': str, 'level_cn': str, 'direction': str,
         'strength_score': float, 'duration_days': int,
         'evidence': list, 'light': str}
    """
    if not symbol:
        return {'level': 'unknown', 'level_cn': '数据不足', 'direction': 'unknown',
                'strength_score': 0, 'duration_days': 0, 'evidence': [], 'light': 'yellow'}

    try:
        end_str = datetime.now().strftime('%Y-%m-%d')
        start_str = (datetime.now() - timedelta(days=15)).strftime('%Y-%m-%d')
        mf_df = self.dm.get_cached_moneyflow(symbol, start_date=start_str, end_date=end_str)
        if mf_df.empty:
            mf_df = self.dm.get_cached_moneyflow(symbol)
        if mf_df.empty or len(mf_df) < 3:
            return {'level': 'unknown', 'level_cn': '数据不足', 'direction': 'unknown',
                    'strength_score': 0, 'duration_days': 0, 'evidence': [], 'light': 'yellow'}

        mf_10 = mf_df.tail(10)
        mf_5 = mf_df.tail(5)

        # 5日净额
        net_5d = float(mf_5['net_lg_amount'].sum())
        # 大单+超大单总额
        total_lg = (mf_5['buy_lg_amount'].abs().sum() + mf_5['sell_lg_amount'].abs().sum()
                     + mf_5['buy_elg_amount'].abs().sum() + mf_5['sell_elg_amount'].abs().sum())
        ratio_5d = abs(net_5d) / max(total_lg, 1)
        # 正净额天数
        pos_days = int((mf_5['net_lg_amount'] > 0).sum())
        # 连续净流入天数（从最近往回数）
        streak = 0
        for _, row in mf_5.iloc[::-1].iterrows():
            if row['net_lg_amount'] > 0:
                streak += 1
            else:
                break
        # 方向
        direction = 'inflow' if net_5d > 0 else ('outflow' if net_5d < 0 else 'neutral')

        # 5级分层
        evidence = []
        if net_5d > 0:
            if streak >= 3 and net_5d / 5 > 1e8:  # 连续3日+日均>1亿
                level, level_cn = 'extreme_strong', '极强'
                evidence.append(f'超大单连续{streak}日净流入，5日共{net_5d/1e8:.2f}亿')
                light = 'green'
            elif ratio_5d > 0.4:
                level, level_cn = 'strong', '强'
                evidence.append(f'大单净流入占比{ratio_5d:.0%}，连续{streak}日')
                light = 'green'
            elif pos_days / 5 >= 0.6:
                level, level_cn = 'medium', '中等'
                evidence.append(f'净流入{pos_days}/5天，不完全连续')
                light = 'yellow'
            elif 0.3 <= ratio_5d <= 0.5:
                level, level_cn = 'weak', '弱'
                evidence.append(f'大单流入流出交替（净额占比{ratio_5d:.0%}）')
                light = 'yellow'
            else:
                level, level_cn = 'very_weak', '极弱'
                evidence.append(f'5日净流入极小（{net_5d/1e4:.0f}万）')
                light = 'yellow'
        elif net_5d < 0:
            if streak >= 3:
                level, level_cn = 'extreme_outflow', '极强流出'
                evidence.append(f'连续{streak}日净流出')
                light = 'red'
            else:
                level, level_cn = 'outflow', '流出'
                evidence.append(f'5日净流出{abs(net_5d)/1e4:.0f}万')
                light = 'red'
        else:
            level, level_cn = 'neutral', '中性'
            evidence.append('5日资金无明显方向')
            light = 'yellow'

        return {
            'level': level, 'level_cn': level_cn,
            'direction': direction,
            'strength_score': round(ratio_5d, 3),
            'duration_days': streak,
            'evidence': evidence,
            'light': light,
        }
    except Exception as e:
        logger.debug(f"get_fund_flow_strength失败 {symbol}: {e}")
        return {'level': 'unknown', 'level_cn': '计算异常', 'direction': 'unknown',
                'strength_score': 0, 'duration_days': 0, 'evidence': [], 'light': 'yellow'}
```

### 2.4 新增方法：MainForceScorer.get_chip_transfer()

**修改文件**：`backend/app/engine/framework/chip_strategy.py`

```python
def get_chip_transfer(self, symbol: str) -> dict:
    """筹码转移检测（364c Phase 3：对应359号§4.4子维度3）

    筹码转移量化（基于LLM Wiki《筹码转移》）：
      向上转移：底部20%筹码20日减少≥5% AND 顶部20%筹码20日增加≥5%
      向下转移：顶部20%筹码20日减少≥5% AND 底部20%筹码20日增加≥5%
      稳定：变化均<5%

    转移速度：
      >1%/天 = 加速
      0.3-1%/天 = 正常
      <0.3%/天 = 缓慢

    实现方式：
      通过近20日与前20日（T-40~-20）的ASR/cyqkl/获利盘变化间接推断。
      直接筹码分布历史不可用（ChipDistributionService仅计算当日），
      用资金流向方向+价格位置变化+筹码指标变化三重证据近似推断。
    """
    if not symbol:
        return {'direction': 'unknown', 'speed': 0, 'speed_level': '未知',
                'evidence': [], 'light': 'yellow'}

    try:
        # 资金流向方向（主力买入=筹码向上转移的必要条件）
        mf_df = self.dm.get_cached_moneyflow(symbol)
        if mf_df is None or mf_df.empty or len(mf_df) < 20:
            return {'direction': 'unknown', 'speed': 0, 'speed_level': '未知',
                    'evidence': ['数据不足'], 'light': 'yellow'}

        mf_20 = mf_df.tail(20)
        mf_prev20 = mf_df.iloc[-40:-20] if len(mf_df) >= 40 else mf_df.head(20)

        net_20d_recent = float(mf_20['net_lg_amount'].sum())
        net_20d_prev = float(mf_prev20['net_lg_amount'].sum())

        # 价格位置变化
        df = self.dm.get_cached_daily_data(symbol)
        if df is None or df.empty or len(df) < 40:
            return {'direction': 'unknown', 'speed': 0, 'speed_level': '未知',
                    'evidence': ['K线数据不足'], 'light': 'yellow'}

        closes = df['close'].values
        price_20d_ago = float(closes[-20])
        price_now = float(closes[-1])
        price_change_pct = (price_now - price_20d_ago) / price_20d_ago if price_20d_ago > 0 else 0

        evidence = []
        direction = 'stable'
        speed = 0

        # 推断逻辑
        if net_20d_recent > 0 and price_change_pct > 0:
            # 主力净流入 + 价格上涨 → 筹码向上转移
            direction = 'upward'
            speed = abs(net_20d_recent) / max(abs(net_20d_prev), 1) * abs(price_change_pct)
            evidence.append(f'主力20日净流入{net_20d_recent/1e4:.0f}万+价格涨{price_change_pct:.1%}')
        elif net_20d_recent < 0 and price_change_pct < 0:
            # 主力净流出 + 价格下跌 → 筹码向下转移
            direction = 'downward'
            speed = abs(net_20d_recent) / max(abs(net_20d_prev), 1) * abs(price_change_pct)
            evidence.append(f'主力20日净流出{abs(net_20d_recent)/1e4:.0f}万+价格跌{abs(price_change_pct):.1%}')
        elif net_20d_recent > 0 and price_change_pct <= 0:
            # 主力净流入但价格不涨 → 可能在吸筹蓄势
            direction = 'accumulating'
            speed = abs(net_20d_recent) / 1e8  # 以亿为单位
            evidence.append(f'主力净流入但价格未涨，可能在吸筹蓄势')
        else:
            direction = 'stable'
            evidence.append('筹码无明显转移迹象')

        # 速度分级
        if speed > 0.01:
            speed_level = '加速'
        elif speed > 0.003:
            speed_level = '正常'
        else:
            speed_level = '缓慢'

        light = 'green' if direction == 'upward' else ('red' if direction == 'downward' else 'yellow')

        return {
            'direction': direction,
            'speed': round(speed, 4),
            'speed_level': speed_level,
            'evidence': evidence,
            'light': light,
        }
    except Exception as e:
        logger.debug(f"get_chip_transfer失败 {symbol}: {e}")
        return {'direction': 'unknown', 'speed': 0, 'speed_level': '异常',
                'evidence': [str(e)], 'light': 'yellow'}
```

### 2.5 新增方法：MainForceScorer.get_control_degree()

**修改文件**：`backend/app/engine/framework/chip_strategy.py`

```python
def get_control_degree(self, symbol: str) -> dict:
    """控盘度计算（364c Phase 3：对应LLM Wiki《跟庄战法》精气神三维度+控盘度）

    控盘度 = f(筹码集中度, 价格稳定性, 主力持有比例估算)

    计算公式：
      control_score = 0.4 × concentration_score    # 筹码集中度
                   + 0.3 × price_stability_score   # 价格稳定性
                   + 0.3 × force_estimate_score    # 主力持有估算

    Returns:
        {'score': float(0-10), 'level': str, 'detail': dict, 'evidence': list, 'light': str}
    """
    if not symbol:
        return {'score': 0, 'level': '数据不足', 'detail': {}, 'evidence': [], 'light': 'yellow'}

    try:
        # 1. 筹码集中度分（0-10）
        concentration_score = 5.0  # 默认中等
        holder_detail = {}
        try:
            holder_df = self.dm.get_cached_stk_holder(symbol)
            if not holder_df.empty and 'holder_number' in holder_df.columns:
                h = holder_df.dropna(subset=['holder_number']).sort_values('end_date')
                if len(h) >= 2:
                    latest = float(h['holder_number'].iloc[-1])
                    prev = float(h['holder_number'].iloc[-2])
                    if prev > 0:
                        change = (latest - prev) / prev
                        if change < -0.10:
                            concentration_score = 9.0
                        elif change < -0.05:
                            concentration_score = 7.5
                        elif change < -0.02:
                            concentration_score = 6.0
                        elif change < 0:
                            concentration_score = 5.0
                        else:
                            concentration_score = 3.0
                        holder_detail['holder_change'] = round(change * 100, 2)
        except Exception:
            pass

        # 如果没有股东户数，用OHLCV稳定性
        if not holder_detail:
            df = self.dm.get_cached_daily_data(symbol)
            if df is not None and not df.empty and len(df) >= 20:
                closes = df['close'].values
                cv = np.std(closes[-20:]) / max(np.mean(closes[-20:]), 1e-9)
                if cv < 0.03:
                    concentration_score = 7.0  # 低波动=高集中度
                elif cv < 0.05:
                    concentration_score = 5.0
                else:
                    concentration_score = 3.0
                holder_detail['price_cv'] = round(cv, 4)

        # 2. 价格稳定性分（0-10）
        price_stability_score = 5.0
        df = self.dm.get_cached_daily_data(symbol)
        if df is not None and not df.empty and len(df) >= 60:
            closes = df['close'].values
            # 20日振幅
            amplitude = (np.max(closes[-20:]) - np.min(closes[-20:])) / np.mean(closes[-20:])
            if amplitude < 0.05:
                price_stability_score = 8.0
            elif amplitude < 0.10:
                price_stability_score = 6.0
            elif amplitude < 0.20:
                price_stability_score = 4.0
            else:
                price_stability_score = 2.0
            holder_detail['amplitude_20d'] = round(amplitude * 100, 2)

        # 3. 主力持有估算分（0-10）
        force_estimate_score = 5.0
        mf_score = self._score_moneyflow(symbol)
        if mf_score >= 2.5:
            force_estimate_score = 8.0
        elif mf_score >= 1.5:
            force_estimate_score = 6.0
        elif mf_score >= 0.5:
            force_estimate_score = 4.0
        else:
            force_estimate_score = 2.0
        holder_detail['mf_moneyflow_score'] = round(mf_score, 2)

        # 综合控盘度
        total = (0.4 * concentration_score + 0.3 * price_stability_score + 0.3 * force_estimate_score)

        if total >= 7.5:
            level = '高度控盘'
            light = 'green'
        elif total >= 5.0:
            level = '中度控盘'
            light = 'yellow'
        elif total >= 3.0:
            level = '低度控盘'
            light = 'yellow'
        else:
            level = '无控盘迹象'
            light = 'red'

        evidence = []
        if concentration_score >= 7:
            evidence.append(f'筹码集中度高（股东户数减少{holder_detail.get("holder_change", "?")}%）')
        if price_stability_score >= 7:
            evidence.append(f'价格波动小（20日振幅{holder_detail.get("amplitude_20d", "?")}%）')
        if force_estimate_score >= 7:
            evidence.append(f'主力资金关注度高（moneyflow评分{mf_score:.1f}）')

        return {
            'score': round(total, 2),
            'level': level,
            'detail': holder_detail,
            'evidence': evidence or ['控盘度中等'],
            'light': light,
        }
    except Exception as e:
        logger.debug(f"get_control_degree失败 {symbol}: {e}")
        return {'score': 0, 'level': '计算异常', 'detail': {}, 'evidence': [str(e)], 'light': 'yellow'}
```

### 2.6 新增文件：fund_chip_builder.py

位置：`backend/app/opportunity_atlas/fund_chip_builder.py`

```python
"""fund_chip_builder.py — 第4维资金筹码输出结构化构建器

364c Phase 3：将资金筹码维度拆解为6个子维度的结构化输出。
"""
from __future__ import annotations
import json
import logging
from typing import Any, Optional

logger = logging.getLogger(__name__)


def build_fund_chip_segment(
    dims: dict,
    tags: dict,
    sub_scores: dict,
    fund_flow: dict,
    chip_transfer: dict,
    control_degree: dict,
    l0: dict,
) -> dict:
    """构建第4维资金筹码结构化段落

    Args:
        dims: status_engine的dim_states（含chip_fund等）
        tags: pre_feat_cache扁平化标签
        sub_scores: MainForceScorer.get_sub_scores()输出
        fund_flow: MainForceScorer.get_fund_flow_strength()输出
        chip_transfer: MainForceScorer.get_chip_transfer()输出
        control_degree: MainForceScorer.get_control_degree()输出
        l0: L0风险分级输出

    Returns:
        {'title', 'light', 'judgment', 'audit', 'text', 'plain', 'data': {...}}
    """
    # 1. 主力行为阶段（从dims或tags获取）
    phase_info = _extract_phase_info(dims, tags)

    # 2. 资金流向强度（已有fund_flow）

    # 3. 成本分布结构
    cost_structure = _extract_cost_structure(sub_scores, tags)

    # 4. 筹码信号状态
    signal_info = _extract_signal_info(tags)

    # 5. 散户与机构博弈
    retail_inst = _extract_retail_institution(sub_scores)

    # 6. 融资杠杆变化
    margin_info = _extract_margin_info(tags)

    # 红绿灯综合判定
    overall_light = _judge_overall_light(phase_info, fund_flow, chip_transfer, control_degree, l0)

    # 条件稽核
    conditions = _build_conditions(phase_info, fund_flow, cost_structure, chip_transfer, control_degree)
    satisfied = sum(1 for c in conditions if c['satisfied'])

    # plain白话
    plain = _fund_chip_plain(phase_info, fund_flow, cost_structure, chip_transfer, control_degree)

    _l = {'green': '✅', 'yellow': '⚠️', 'red': '🚫'}

    return {
        'title': '资金与筹码状态',
        'light': _l.get(overall_light, '⚠️'),
        'judgment': phase_info.get('stage_cn', '未知'),
        'audit': {
            'conditions': conditions,
            'satisfied_count': satisfied,
            'total_count': len(conditions),
            'confidence': round(satisfied / max(len(conditions), 1), 2),
        },
        'text': (f"主力阶段：{phase_info.get('stage_cn', '未知')}; "
                 f"资金流向：{fund_flow.get('level_cn', '未知')}; "
                 f"控盘度：{control_degree.get('level', '未知')}"),
        'plain': plain,
        'data': {
            'phase': phase_info,
            'fund_flow': fund_flow,
            'cost_structure': cost_structure,
            'signal': signal_info,
            'retail_institution': retail_inst,
            'margin': margin_info,
            'chip_transfer': chip_transfer,
            'control_degree': control_degree,
            'sub_scores': sub_scores,
        },
    }


def _extract_phase_info(dims: dict, tags: dict) -> dict:
    """提取主力行为阶段信息"""
    cf = dims.get('chip_fund', {})
    state = cf.get('state', '中性')
    stage_map = {
        '流入': ('建仓期', 'building'),
        '流出': ('出货期', 'distributing'),
    }
    stage_cn, stage_en = stage_map.get(state, ('中性', 'neutral'))

    # 从tags补充
    mfp = str(tags.get('main_force_phase', ''))
    phase_map = {
        'building': ('建仓期', 'building'),
        'washing': ('洗盘期', 'washing'),
        'lifting': ('拉升期', 'lifting'),
        'distributing': ('出货期', 'distributing'),
    }
    if mfp in phase_map:
        stage_cn, stage_en = phase_map[mfp]

    return {
        'stage_cn': stage_cn,
        'stage_en': stage_en,
        'confidence': cf.get('confidence', 0.5),
        'evidence': cf.get('evidence', []),
        'light': cf.get('light', 'yellow'),
    }


def _extract_cost_structure(sub_scores: dict, tags: dict) -> dict:
    """提取成本分布结构"""
    chip_detail = (sub_scores.get('sub_details', {}) or {}).get('chip_indicators', {})
    asr = chip_detail.get('asr')
    ssrp = chip_detail.get('ssrp')
    concentration = chip_detail.get('concentration')

    return {
        'asr': asr,
        'ssrp': ssrp,
        'concentration': concentration,
        'chip_distribution_score': sub_scores.get('chip_distribution', 0),
    }


def _extract_signal_info(tags: dict) -> dict:
    """提取筹码信号状态"""
    buy_sell = str(tags.get('buy_sell_point', ''))
    signal_type = 'none'
    if '三买' in buy_sell or 'buy' in buy_sell.lower():
        signal_type = 'S_BUY'
    elif '三卖' in buy_sell or 'sell' in buy_sell.lower():
        signal_type = 'S_SELL'

    return {
        'current_signal': signal_type,
        'description': buy_sell or '无信号',
    }


def _extract_retail_institution(sub_scores: dict) -> dict:
    """提取散户与机构博弈"""
    return {
        'retail_contrarian_score': sub_scores.get('retail_contrarian', 0),
        'lhb_score': sub_scores.get('lhb', 0),
    }


def _extract_margin_info(tags: dict) -> dict:
    """提取融资杠杆变化"""
    return {
        'margin_detail': tags.get('margin_detail', '无数据'),
    }


def _judge_overall_light(phase_info, fund_flow, chip_transfer, control_degree, l0) -> str:
    """综合判定第4维红绿灯"""
    if l0.get('hard_veto'):
        return 'red'

    green_count = 0
    red_count = 0

    if phase_info.get('light') == 'green':
        green_count += 1
    elif phase_info.get('light') == 'red':
        red_count += 1

    if fund_flow.get('light') == 'green':
        green_count += 1
    elif fund_flow.get('light') == 'red':
        red_count += 1

    if chip_transfer.get('light') == 'green':
        green_count += 1
    elif chip_transfer.get('light') == 'red':
        red_count += 1

    if control_degree.get('light') == 'green':
        green_count += 1
    elif control_degree.get('light') == 'red':
        red_count += 1

    if red_count >= 2:
        return 'red'
    if green_count >= 2:
        return 'green'
    return 'yellow'


def _build_conditions(phase_info, fund_flow, cost_structure, chip_transfer, control_degree) -> list:
    """构建条件稽核列表"""
    conditions = []

    # 主力阶段条件
    conditions.append({
        'name': '主力阶段',
        'satisfied': phase_info.get('stage_en') in ('building', 'lifting'),
        'actual': phase_info.get('stage_cn', '未知'),
        'threshold': '建仓期或拉升期',
        'detail': f"当前阶段={phase_info.get('stage_cn')}"
    })

    # 资金流向条件
    conditions.append({
        'name': '资金流向',
        'satisfied': fund_flow.get('direction') == 'inflow',
        'actual': fund_flow.get('level_cn', '未知'),
        'threshold': '净流入',
        'detail': fund_flow.get('evidence', [''])[0] if fund_flow.get('evidence') else ''
    })

    # 筹码集中度条件
    conditions.append({
        'name': '筹码集中度',
        'satisfied': control_degree.get('score', 0) >= 5.0,
        'actual': f"控盘度{control_degree.get('score', 0):.1f}/10",
        'threshold': '≥5.0',
        'detail': control_degree.get('level', '未知')
    })

    # 筹码转移条件
    conditions.append({
        'name': '筹码转移方向',
        'satisfied': chip_transfer.get('direction') in ('upward', 'accumulating'),
        'actual': chip_transfer.get('direction', '未知'),
        'threshold': '向上转移或吸筹蓄势',
        'detail': chip_transfer.get('evidence', [''])[0] if chip_transfer.get('evidence') else ''
    })

    return conditions


def _fund_chip_plain(phase_info, fund_flow, cost_structure, chip_transfer, control_degree) -> str:
    """第4维plain白话文本"""
    parts = [f"主力处于{phase_info.get('stage_cn', '未知')}"]

    if fund_flow.get('level_cn') not in ('数据不足', '未知', '计算异常'):
        parts.append(f"资金{fund_flow.get('level_cn')}（{fund_flow.get('direction', '未知')}）")

    if control_degree.get('level') not in ('数据不足', '计算异常'):
        parts.append(f"控盘度{control_degree.get('level')}")

    if chip_transfer.get('direction') not in ('unknown',):
        dir_map = {'upward': '筹码向上转移', 'downward': '筹码向下转移',
                   'accumulating': '可能在吸筹蓄势', 'stable': '筹码稳定'}
        parts.append(dir_map.get(chip_transfer['direction'], ''))

    return '，'.join(p for p in parts if p)
```

### 2.7 修改：status_engine中chip_fund维度输出

**修改文件**：`backend/app/opportunity_atlas/status_engine.py`

**修改行号**：254-263（chip_fund维度判定，保留状态输出但丰富evidence）

```python
# 旧代码（L254-263）保持state输出不变
# 但在build_seven_dim_report()中升级fund_chip段落（见2.8）
```

### 2.8 修改：build_seven_dim_report()中fund_chip段落

**修改文件**：`backend/app/opportunity_atlas/status_engine.py`

**修改行号**：638-639（替换fund_chip段落构建）

```python
# 旧代码（L638-639）:
'seg': _seg('资金与筹码状态', dims.get('chip_fund', {}).get('light', 'yellow'),
            f"筹码资金：{dims.get('chip_fund', {}).get('state', '中性')}",
            '谁在买、筹码状态'),

# 新代码（364c Phase 3）:
'fund_chip': _build_fund_chip_segment_from_snapshot(dims, tags, snapshot_row),
```

**新增辅助函数**：

```python
def _build_fund_chip_segment_from_snapshot(dims, tags, snapshot_row) -> dict:
    """第4维资金筹码结构化段落（从snapshot数据构建）"""
    from app.opportunity_atlas.fund_chip_builder import build_fund_chip_segment

    try:
        # 获取MainForceScorer子评分
        from app.engine.framework.chip_strategy import MainForceScorer
        scorer = MainForceScorer()

        # 获取K线数据
        ts_code = snapshot_row.get('ts_code', '')
        df = None
        try:
            from app.data import DataManager
            dm = DataManager()
            df = dm.get_cached_daily_data(ts_code)
        except Exception:
            pass

        sub_scores = scorer.get_sub_scores(df, symbol=ts_code) if df is not None else {}
        fund_flow = scorer.get_fund_flow_strength(ts_code)
        chip_transfer = scorer.get_chip_transfer(ts_code)
        control_degree = scorer.get_control_degree(ts_code)

        # l0从snapshot获取
        try:
            l0 = json.loads(snapshot_row.get('l0') or '{}')
        except Exception:
            l0 = {}

        return build_fund_chip_segment(
            dims=dims, tags=tags, sub_scores=sub_scores,
            fund_flow=fund_flow, chip_transfer=chip_transfer,
            control_degree=control_degree, l0=l0,
        )
    except Exception as e:
        logger.debug(f"fund_chip段落构建失败: {e}")
        # 回退到简单输出
        _l = {'green': '✅', 'yellow': '⚠️', 'red': '🚫'}
        cf = dims.get('chip_fund', {})
        return {
            'title': '资金与筹码状态',
            'light': _l.get(cf.get('light', 'yellow'), '⚠️'),
            'judgment': cf.get('state', '中性'),
            'audit': {'conditions': [], 'satisfied_count': 0, 'total_count': 0, 'confidence': 0},
            'text': f"筹码资金：{cf.get('state', '中性')}",
            'plain': f"资金面{cf.get('state', '中性')}",
            'data': {},
        }
```

---

## 三、调用链变更

```
旧链路：
  MainForceScorer.score(data) → float（总分0-10）
  PhaseDetectionEngine.compute_tags() → {main_force_phase, ...}
  status_engine._build_dimensions() → dims['chip_fund'] = {state, light, confidence, evidence}
  status_engine.build_seven_dim_report() → fund_chip段落（简单拼接）

新链路：
  MainForceScorer.score(data) → float（保持不变）
  MainForceScorer.get_sub_scores(data, symbol) → dict（新增：6子维度独立分值+详情）
  MainForceScorer.get_fund_flow_strength(symbol) → dict（新增：5级强度分层）
  MainForceScorer.get_chip_transfer(symbol) → dict（新增：筹码转移检测）
  MainForceScorer.get_control_degree(symbol) → dict（新增：控盘度计算）
  PhaseDetectionEngine.compute_tags() → dict（保持不变）
  status_engine._build_dimensions() → dims['chip_fund']（保持不变）
  status_engine.build_seven_dim_report() → fund_chip段落（调用fund_chip_builder）
  fund_chip_builder.build_fund_chip_segment() → 结构化6子维度输出
```

**关键变更**：
- MainForceScorer新增4个方法（get_sub_scores/get_fund_flow_strength/get_chip_transfer/get_control_degree）
- 新增 `fund_chip_builder.py` 模块
- `build_seven_dim_report()` 中 fund_chip 段落从简单拼接升级为结构化构建

---

## 四、测试用例

### 4.1 单元测试

| 测试项 | 输入 | 预期输出 |
|--------|------|---------|
| get_sub_scores-正常 | 120日OHLCV DataFrame | total=0-10, 6子维度各有分值 |
| get_sub_scores-数据不足 | 30日DataFrame | total=0.0 |
| get_fund_flow_strength-极强 | symbol含3日连续净流入>1亿 | level='extreme_strong' |
| get_fund_flow_strength-极弱 | symbol含5日净额极小 | level='very_weak' |
| get_chip_transfer-向上 | 主力净流入+价格上涨 | direction='upward' |
| get_chip_transfer-稳定 | 无明显变化 | direction='stable' |
| get_control_degree-高控盘 | 股东户数减少>10%+低波动 | score≥7.5, level='高度控盘' |
| get_control_degree-无控盘 | 股东户数增加+高波动 | score<3.0 |
| fund_chip_builder综合 | 正常输入 | 6子维度结构化输出 |
| plain文本 | 正常输入 | 包含主力阶段+资金流向+控盘度 |

### 4.2 集成测试

1. 运行全量pytest确认无回归
2. 调用`/api/v3/strategy-analyze`接口，验证返回的seven_dim_report.fund_chip段落包含：
   - `audit`字段（4条条件稽核）
   - `data.phase`（主力行为阶段）
   - `data.fund_flow`（5级强度）
   - `data.cost_structure`（ASR/SSRP/浓度）
   - `data.chip_transfer`（筹码转移方向+速度）
   - `data.control_degree`（控盘度评分+级别）
   - `data.sub_scores`（MainForceScorer 6子维度分值）
3. 浏览器验证indicator-ide.html正确渲染6子维度

---

## 五、实施步骤

| 步骤 | 内容 | 工作量 |
|------|------|:------:|
| 1 | MainForceScorer.get_sub_scores()方法 | 1.5h |
| 2 | MainForceScorer._build_sub_details()方法 | 1h |
| 3 | MainForceScorer.get_fund_flow_strength()方法（5级分层） | 1.5h |
| 4 | MainForceScorer.get_chip_transfer()方法（筹码转移检测） | 1.5h |
| 5 | MainForceScorer.get_control_degree()方法（控盘度计算） | 1.5h |
| 6 | 新建fund_chip_builder.py（段落构建器） | 1.5h |
| 7 | 修改build_seven_dim_report() fund_chip段落 | 0.5h |
| 8 | 单元测试+集成测试 | 1h |
| **合计** | | **10h** |

---

## 修订记录

| 版本 | 日期 | 修订内容 |
|------|------|---------|
| v1.0 | 2026-08-21 | 初版：6子维度结构化+get_sub_scores()+5级资金分层+筹码转移+控盘度+条件稽核 |
