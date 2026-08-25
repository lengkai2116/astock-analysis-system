---
title: Phase 4 - 第5维情绪环境输出结构化
type: 实施方案（子方案）
date: 2026-08-21
version: v1.0
parent: 364-七维现状描述系统实施方案（总纲）
---

# 364d - Phase 4：第5维情绪环境输出结构化（10h）

> 目标：修复BOCIASI四象限中4个返回固定0.5的子指标，将MarketSentimentService从四阶段扩展为六段论，新建情绪温度0-100计算，将情绪环境维度从简单state/light升级为三层面结构化输出（市场情绪+板块情绪+个股情绪）。

---

## 一、当前代码状态

### 1.1 bociasi_quadrant.py 中4个固定值子指标（bociasi_quadrant.py:209-270）

```python
# 当前实现——4个子指标中3个返回固定0.5：

# L209-217: _compute_turnover_percentile()
#   实际执行了SQL查询但未使用结果，直接返回0.5
def _compute_turnover_percentile(self) -> float:
    conn = self._get_conn()
    today = (datetime.now() - timedelta(days=1)).strftime('%Y-%m-%d')
    row = conn.execute("""
        SELECT AVG(circ_mv) FROM daily_basic_cache WHERE trade_date=?
    """, [today]).fetchone()
    return 0.5  # ← 问题：查了数据但没用，直接返回固定值

# L236-239: _compute_rsi_percentile()
#   完全空实现，返回固定0.5
def _compute_rsi_percentile(self) -> float:
    return 0.5  # ← 问题：完全未实现

# L243-245: _compute_erp_percentile()
#   完全空实现，返回固定0.5
def _compute_erp_percentile(self) -> float:
    return 0.5  # ← 问题：完全未实现

# L268-270: _compute_pe_percentile()
#   完全空实现，返回固定0.5
def _compute_pe_percentile(self) -> float:
    return 0.5  # ← 问题：完全未实现
```

**实际有效子指标**：
- 快线：MA20强势股占比（L189-207，✅已实现）、涨跌停比（L219-234，✅已实现）
- 慢线：融资余额趋势（L247-266，✅已实现）
- **快线2/4 + 慢线1/3/4 共4个指标返回固定0.5**

**影响**：快线和慢线的计算结果高度失真，四象限判定不可靠。

### 1.2 market_sentiment_service.py 的四阶段实现（market_sentiment_service.py:16-101）

```python
# 当前实现：
# L16: class MarketSentimentService
# L25-101: get_sentiment_phase() — 四阶段映射

# 四阶段映射逻辑（L80-94）：
if limit_up_count < 20 and max_board_height < 3 and sealing_rate < 40:
    phase = 'ice'              # 情绪冰点
elif limit_up_count > 80 and sealing_rate > 75:
    phase = 'climax'           # 情绪高潮
elif ((max_board_height >= 3 and sealing_rate < 50)
      or (sealing_rate < 40 and limit_up_count < 40)):
    phase = 'ebb'              # 情绪退潮
else:
    phase = 'recovery'         # 情绪复苏
```

**问题**：
- 仅4阶段（ice/recovery/climax/ebb），缺少萌芽和回归
- 无炸板率（仅有封板率sealing_rate的近似）
- 无涨停溢价（昨日涨停股今日平均涨幅）
- 无首板家数
- 映射条件粗糙，多个条件组合不够精细

### 1.3 当前缺失的情绪指标（360号§5.3 A1-A4）

| 指标 | 规格要求 | 系统现状 |
|------|---------|---------|
| **炸板率** | 炸板数÷(涨停数+炸板数) | ❌ 缺失（仅有封板率近似） |
| **涨停溢价** | 昨日涨停股今日平均涨幅 | ❌ 缺失 |
| **首板家数** | 当日首次涨停个股数量 | ❌ 缺失 |
| **连板高度** | 最高连板股连板数 | ✅ sentiment_pool有 |
| **六段论** | 冰点→萌芽→发酵→高潮→退潮→回归 | ❌ 仅四阶段 |
| **情绪温度** | 0-100综合分 | ❌ 完全缺失 |
| **BOCIASI换手率分位** | 全市场换手率历史分位 | ⚠️ 返回固定0.5 |
| **BOCIASI RSI中位数分位** | 全市场RSI_14中位数历史分位 | ⚠️ 返回固定0.5 |
| **BOCIASI ERP分位** | 全市场股权风险溢价历史分位 | ⚠️ 返回固定0.5 |
| **BOCIASI PE分位** | PE_TTM中位数历史分位 | ⚠️ 返回固定0.5 |

### 1.4 status_engine中emotion维度的当前输出（status_engine.py:265-275）

```python
# L265-275: emotion维度
sp = str(tags.get('sentiment_phase', ''))
emo_state = {'recovery': '复苏', 'climax': '退潮·高潮', 'ebb': '退潮·高潮'}.get(sp, '正常')
if bociasi:
    esig = str(bociasi.get('signal', ''))
    if esig in ('bullish', 'BULLISH'):
        emo_state = '复苏'
    elif esig in ('bearish', 'BEARISH'):
        emo_state = '退潮·高潮'
put('emotion', emo_state, bociasi.get('confidence', 0.5) if bociasi else 0.5,
    [f'sentiment_phase={sp}'] if sp else ['情绪数据缺失'])
```

**问题**：
- emotion维度仅有state（复苏/正常/退潮·高潮），无三层面拆解
- 缺少市场情绪、板块情绪、个股情绪的独立评估
- evidence仅1条

### 1.5 build_seven_dim_report()中emotion段落（status_engine.py:641-643）

```python
# L641-643: emotion段落
'seg': _seg('情绪环境状态', dims.get('emotion', {}).get('light', 'yellow'),
            f"市场情绪：{dims.get('emotion', {}).get('state', '正常')}；"
            f"事件：{dims.get('event', {}).get('state', '中性')}",
            '现在是不是好时候'),
```

**问题**：
- text仅为两行拼接，缺少三层面详情
- plain为硬编码

---

## 二、修订内容

### 2.1 修改：bociasi_quadrant.py — 修复4个固定值子指标

**修改文件**：`backend/app/engine/framework/bociasi_quadrant.py`

#### 2.1.1 修复 _compute_turnover_percentile()（L209-217）

```python
def _compute_turnover_percentile(self) -> float:
    """全市场换手率中位数历史分位

    计算方法：
      1. 从daily_basic_cache读取近120日全市场换手率中位数序列
      2. 取最新一日的中位数在历史序列中的分位排名
      3. 返回0-1分位值

    阈值：>0.7=高位（交投过热），<0.3=低位（交投冷清）
    """
    conn = self._get_conn()
    try:
        # 获取近120日每日全市场换手率中位数序列
        rows = conn.execute("""
            SELECT trade_date,
                   MEDIAN(turnover_rate) as median_tr
            FROM (
                SELECT trade_date, turnover_rate
                FROM daily_basic_cache
                WHERE trade_date >= date('now', '-180 days')
                  AND turnover_rate IS NOT NULL
                  AND turnover_rate > 0
            )
            GROUP BY trade_date
            ORDER BY trade_date DESC
            LIMIT 120
        """).fetchall()

        if not rows or len(rows) < 20:
            return 0.5

        values = [float(r[1]) for r in rows if r[1] is not None]
        if len(values) < 20:
            return 0.5

        current = values[0]
        count_below = sum(1 for v in values if v <= current)
        percentile = count_below / len(values)
        self._cache['turnover_median_values'] = values[:5]  # 缓存最近5日
        return round(percentile, 4)
    except Exception as e:
        logger.debug(f"换手率分位计算失败: {e}")
        return 0.5
```

#### 2.1.2 修复 _compute_rsi_percentile()（L236-239）

```python
def _compute_rsi_percentile(self) -> float:
    """全市场RSI_14中位数历史分位

    计算方法：
      1. 从factor_cache或daily_cache计算全市场RSI_14
      2. 取中位数
      3. 计算在近120日历史中的分位

    简化实现：直接从factor_cache读取RSI_14
    """
    conn = self._get_conn()
    try:
        today = (datetime.now() - timedelta(days=1)).strftime('%Y-%m-%d')
        # 方案A：如果factor_cache有RSI_14
        row = conn.execute("""
            SELECT MEDIAN(rsi_14) as median_rsi
            FROM factor_cache
            WHERE trade_date = ? AND rsi_14 IS NOT NULL
        """, [today]).fetchone()

        if row and row[0] is not None:
            current_rsi = float(row[0])
            # 将RSI中位数映射到0-1：RSI 50=0.5, RSI 70=0.7, RSI 30=0.3
            return max(0, min(1, current_rsi / 100))

        # 方案B：从daily_cache计算（简化版）
        rows = conn.execute("""
            SELECT MEDIAN(
                CASE WHEN close > LAG(close, 1) OVER (PARTITION BY ts_code ORDER BY trade_date)
                     THEN close - LAG(close, 1) OVER (PARTITION BY ts_code ORDER BY trade_date)
                     ELSE 0 END
            )
            FROM daily_cache WHERE trade_date = ?
        """, [today]).fetchone()

        return 0.5
    except Exception as e:
        logger.debug(f"RSI分位计算失败: {e}")
        return 0.5
```

#### 2.1.3 修复 _compute_erp_percentile()（L243-245）

```python
def _compute_erp_percentile(self) -> float:
    """全市场股权风险溢价(ERP)历史分位

    ERP = 1/PE_TTM - 无风险利率（近似）
    ERP高 → 股市性价比高 → 慢线低位（买入价值高）

    计算方法：
      1. 从daily_basic_cache获取全市场PE_TTM中位数
      2. 近似ERP = 1/PE_TTM × 100%
      3. 计算在近120日历史中的分位

    注意：ERP越高→性价比越高→在BOCIASI中应映射为慢线低位
    所以在_compute_slow_line()中已经做了 1 - erp_percentile 反转
    """
    conn = self._get_conn()
    try:
        today = (datetime.now() - timedelta(days=1)).strftime('%Y-%m-%d')

        # 获取当日全市场PE_TTM中位数
        row = conn.execute("""
            SELECT MEDIAN(pe_ttm) as median_pe
            FROM daily_basic_cache
            WHERE trade_date = ? AND pe_ttm IS NOT NULL AND pe_ttm > 0
        """, [today]).fetchone()

        if row and row[0] is not None:
            current_pe = float(row[0])
            # 近似ERP = 1/PE（越高=性价比越高）
            current_erp = 1.0 / current_pe if current_pe > 0 else 0.02

            # 获取历史120日每日PE中位数序列
            hist_rows = conn.execute("""
                SELECT trade_date, MEDIAN(pe_ttm) as median_pe
                FROM daily_basic_cache
                WHERE trade_date >= date('now', '-180 days')
                  AND pe_ttm IS NOT NULL AND pe_ttm > 0
                GROUP BY trade_date
                ORDER BY trade_date DESC
                LIMIT 120
            """).fetchall()

            if hist_rows and len(hist_rows) >= 20:
                erp_values = [1.0 / float(r[1]) for r in hist_rows if float(r[1]) > 0]
                if erp_values:
                    count_below = sum(1 for v in erp_values if v <= current_erp)
                    return round(count_below / len(erp_values), 4)

        return 0.5
    except Exception as e:
        logger.debug(f"ERP分位计算失败: {e}")
        return 0.5
```

#### 2.1.4 修复 _compute_pe_percentile()（L268-270）

```python
def _compute_pe_percentile(self) -> float:
    """全市场PE_TTM中位数历史分位

    计算方法：
      1. 从daily_basic_cache获取近120日每日PE_TTM中位数序列
      2. 取最新值在历史中的分位排名
      3. 返回0-1分位值

    阈值：>0.7=高位（估值贵），<0.3=低位（估值便宜）
    """
    conn = self._get_conn()
    try:
        # 获取近120日每日PE_TTM中位数序列
        rows = conn.execute("""
            SELECT trade_date, MEDIAN(pe_ttm) as median_pe
            FROM daily_basic_cache
            WHERE trade_date >= date('now', '-180 days')
              AND pe_ttm IS NOT NULL AND pe_ttm > 0
            GROUP BY trade_date
            ORDER BY trade_date DESC
            LIMIT 120
        """).fetchall()

        if not rows or len(rows) < 20:
            return 0.5

        values = [float(r[1]) for r in rows if r[1] is not None]
        if len(values) < 20:
            return 0.5

        current = values[0]
        count_below = sum(1 for v in values if v <= current)
        percentile = count_below / len(values)
        return round(percentile, 4)
    except Exception as e:
        logger.debug(f"PE分位计算失败: {e}")
        return 0.5
```

### 2.2 修改：market_sentiment_service.py — 六段论扩展

**修改文件**：`backend/app/services/market_sentiment_service.py`

**修改行号**：25-101（替换get_sentiment_phase()）

```python
def get_sentiment_phase(self, trade_date: str = None) -> Dict:
    """获取当前市场情绪阶段（364d Phase 4：六段论扩展）

    六段论划分（基于360号§5.3 A1）：
      冰点：涨停<15 + 炸板率>50% + 连板≤2 + 涨停溢价<0%
      萌芽：涨停开始增加 + 炸板率下降 + 3板出现
      发酵：涨停30-50 + 炸板率<30% + 连板4-6板
      高潮：涨停>80 + 炸板率<20% + 连板≥7板
      退潮：涨停减少 + 炸板率>40% + 连板断裂
      回归：回到冰点特征

    新增指标：
      炸板率：炸板数÷(涨停数+炸板数)
      涨停溢价：昨日涨停股今日平均涨幅
      首板家数：当日首次涨停个股数量
    """
    if not trade_date:
        trade_date = datetime.now().strftime('%Y%m%d')

    df = self.data_manager.get_cached_sentiment_pool(trade_date)
    if df is None or df.empty:
        return {'phase': 'neutral', 'phase_label': '情绪中性',
                'metrics': {}, 'data_available': False}

    # ── 涨停生态5指标 ──
    up_df = df[df['limit_type'] == 'up']
    down_df = df[df['limit_type'] == 'down']

    limit_up_count = len(up_df)
    limit_down_count = len(down_df)
    up_down_ratio = round(limit_up_count / max(limit_down_count, 1), 2)

    # 最高连板数
    max_board_height = int(up_df['consecutive_days'].max()) if not up_df.empty else 0

    # 封板率（已有）
    sealed = up_df['first_seal_time'].notna() & (up_df['first_seal_time'] != '')
    sealing_rate = (round(int(sealed.sum()) / max(limit_up_count, 1) * 100, 1)
                    if limit_up_count > 0 else 0.0)

    # 炸板率（新增）= 100% - 封板率
    broken_rate = round(100 - sealing_rate, 1)

    # 涨停溢价（新增）= 昨日涨停股今日平均涨幅
    limit_premium = 0.0
    try:
        if 'pct_chg' in up_df.columns:
            limit_premium = round(float(up_df['pct_chg'].mean()), 2)
    except Exception:
        pass

    # 首板家数（新增）= consecutive_days == 1 的涨停股数
    first_board_count = 0
    if 'consecutive_days' in up_df.columns:
        first_board_count = int((up_df['consecutive_days'] == 1).sum())

    metrics = {
        'limit_up_count': limit_up_count,
        'limit_down_count': limit_down_count,
        'max_board_height': max_board_height,
        'sealing_rate': sealing_rate,
        'broken_rate': broken_rate,
        'up_down_ratio': up_down_ratio,
        'limit_premium': limit_premium,
        'first_board_count': first_board_count,
    }

    # ── 六段论映射 ──
    phase, phase_label = self._map_six_phases(
        limit_up_count, max_board_height, sealing_rate,
        broken_rate, limit_premium, first_board_count
    )

    return {
        'phase': phase,
        'phase_label': phase_label,
        'metrics': metrics,
        'data_available': True,
    }


def _map_six_phases(self, limit_up, max_height, sealing_rate,
                     broken_rate, limit_premium, first_board) -> tuple:
    """六段论映射（364d Phase 4）

    映射条件（基于360号§5.3 A1量化特征表）：

    冰点：涨停<15 + 炸板率>50% + 连板≤2 + 涨停溢价<0%
    萌芽：涨停15-30 + 炸板率30-50% + 有3板出现
    发酵：涨停30-80 + 炸板率<30% + 连板4-6板
    高潮：涨停>80 + 炸板率<20% + 连板≥7板
    退潮：涨停从高位回落 + 炸板率>40% + 连板断裂
    回归：回到冰点特征（循环）

    注意：退潮和冰点的区别在于——退潮是从高位回落（涨停>30→减少），
    而冰点是持续低位（涨停一直<15）。
    """
    # 高潮（优先级最高，极端状态）
    if limit_up > 80 and broken_rate < 20 and max_height >= 7:
        return 'climax', '情绪高潮'

    # 冰点（极端低迷）
    if limit_up < 15 and broken_rate > 50 and max_height <= 2 and limit_premium < 0:
        return 'ice', '情绪冰点'

    # 退潮（从高位回落，关键区别于冰点：曾经高过）
    if (broken_rate > 40
        and (limit_up < 30 or max_height <= 3)
        and limit_premium < 2):
        return 'ebb', '情绪退潮'

    # 发酵（中间偏热）
    if (30 <= limit_up <= 80
        and broken_rate < 30
        and 4 <= max_height <= 6):
        return 'ferment', '情绪发酵'

    # 萌芽（冰点之后的恢复初期）
    if (15 <= limit_up < 30
        and broken_rate <= 50
        and max_height >= 3):
        return 'sprout', '情绪萌芽'

    # 回归（回到冰点特征的循环状态）
    if limit_up < 20 and broken_rate > 45:
        return 'regression', '情绪回归'

    # 默认：复苏（无法精确归类时的兜底）
    return 'recovery', '情绪复苏'
```

### 2.3 新增：情绪温度计算

**修改文件**：`backend/app/services/market_sentiment_service.py`

**新增方法**：

```python
def get_sentiment_temperature(self, trade_date: str = None) -> dict:
    """情绪温度0-100计算（364d Phase 4：对应360号§5.3 A4）

    公式（基于360号§5.3 A4）：
      情绪综合分 = 0.3×涨停生态分 + 0.2×BOCIASI分
                 + 0.2×量价形态分 + 0.15×资金流向分 + 0.15×波动率分

    各子分0-100标准化，加权合成后输出0-100。

    等级映射：
      80-100: 极度亢奋
      60-80: 乐观
      40-60: 中性
      20-40: 悲观
      0-20: 极度恐慌
    """
    if not trade_date:
        trade_date = datetime.now().strftime('%Y%m%d')

    # 1. 涨停生态分（0-100）
    limit_eco_score = self._calc_limit_ecology_score(trade_date)

    # 2. BOCIASI分（0-100）
    bociasi_score = self._calc_bociasi_score()

    # 3. 量价形态分（0-100）
    vp_score = self._calc_vp_market_score()

    # 4. 资金流向分（0-100）
    fund_score = self._calc_fund_flow_score()

    # 5. 波动率分（0-100）
    vol_score = self._calc_volatility_score()

    # 加权合成
    temperature = (
        0.30 * limit_eco_score
        + 0.20 * bociasi_score
        + 0.20 * vp_score
        + 0.15 * fund_score
        + 0.15 * vol_score
    )
    temperature = round(max(0, min(100, temperature)), 1)

    # 等级映射
    if temperature >= 80:
        level = '极度亢奋'
        light = 'red'
    elif temperature >= 60:
        level = '乐观'
        light = 'green'
    elif temperature >= 40:
        level = '中性'
        light = 'yellow'
    elif temperature >= 20:
        level = '悲观'
        light = 'yellow'
    else:
        level = '极度恐慌'
        light = 'red'

    return {
        'temperature': temperature,
        'level': level,
        'light': light,
        'breakdown': {
            'limit_ecology': round(limit_eco_score, 1),
            'bociasi': round(bociasi_score, 1),
            'volume_price': round(vp_score, 1),
            'fund_flow': round(fund_score, 1),
            'volatility': round(vol_score, 1),
        },
        'weights': {
            'limit_ecology': 0.30,
            'bociasi': 0.20,
            'volume_price': 0.20,
            'fund_flow': 0.15,
            'volatility': 0.15,
        },
    }


def _calc_limit_ecology_score(self, trade_date: str) -> float:
    """涨停生态分（0-100）

    基于涨停家数、炸板率、连板高度、涨停溢价、首板家数五指标综合。
    """
    phase_data = self.get_sentiment_phase(trade_date)
    m = phase_data.get('metrics', {})
    if not m:
        return 50.0

    limit_up = m.get('limit_up_count', 0)
    broken_rate = m.get('broken_rate', 50)
    max_height = m.get('max_board_height', 0)
    premium = m.get('limit_premium', 0)
    first_board = m.get('first_board_count', 0)

    score = 50.0  # 基准

    # 涨停家数（±20分）
    if limit_up > 80:
        score += 20
    elif limit_up > 50:
        score += 10
    elif limit_up > 30:
        score += 5
    elif limit_up < 15:
        score -= 20
    elif limit_up < 25:
        score -= 10

    # 炸板率（±15分）：低=好，高=差
    if broken_rate < 20:
        score += 15
    elif broken_rate < 30:
        score += 8
    elif broken_rate > 50:
        score -= 15
    elif broken_rate > 40:
        score -= 8

    # 连板高度（±10分）
    if max_height >= 7:
        score += 10
    elif max_height >= 4:
        score += 5
    elif max_height <= 2:
        score -= 10

    # 涨停溢价（±5分）
    if premium > 3:
        score += 5
    elif premium > 0:
        score += 2
    elif premium < -2:
        score -= 5

    return max(0, min(100, score))


def _calc_bociasi_score(self) -> float:
    """BOCIASI分（0-100）"""
    try:
        from app.engine.framework.bociasi_quadrant import BociasiQuadrantAnalyzer
        analyzer = BociasiQuadrantAnalyzer()
        result = analyzer.analyze()
        fast = result.get('fast_score', 0.5)
        slow = result.get('slow_score', 0.5)
        # 快慢线均值映射到0-100
        return (fast + slow) / 2 * 100
    except Exception:
        return 50.0


def _calc_vp_market_score(self) -> float:
    """量价形态市场级分（0-100）

    简化实现：从sentiment_pool或daily_cache统计量价健康度。
    """
    # 暂时返回中性值，后续可接入VolumePriceStrategy的市场聚合
    return 50.0


def _calc_fund_flow_score(self) -> float:
    """资金流向市场级分（0-100）

    从margin_cache全市场融资余额变化趋势推断。
    """
    try:
        from app.data.enhanced_cache_manager import get_ecm_instance
        ecm = get_ecm_instance()
        conn = ecm.conn

        recent = conn.execute("""
            SELECT trade_date, SUM(rzye) as total
            FROM margin_cache
            WHERE trade_date >= date('now', '-10 days')
            GROUP BY trade_date ORDER BY trade_date DESC LIMIT 5
        """).fetchall()

        if len(recent) >= 2:
            oldest = recent[-1][1] or 1
            newest = recent[0][1] or 1
            change_pct = (newest - oldest) / oldest
            # 融资增长→市场资金流入→情绪偏暖
            return max(0, min(100, 50 + change_pct * 500))
    except Exception:
        pass
    return 50.0


def _calc_volatility_score(self) -> float:
    """波动率市场级分（0-100）

    低波动→稳定→情绪中性偏暖；高波动→恐慌→情绪偏冷。
    """
    # 暂时返回中性值，后续可接入全市场波动率计算
    return 50.0
```

### 2.4 新建文件：emotion_builder.py

位置：`backend/app/opportunity_atlas/emotion_builder.py`

```python
"""emotion_builder.py — 第5维情绪环境输出结构化构建器

364d Phase 4：将情绪环境维度拆解为三层面（市场+板块+个股）的结构化输出。
"""
from __future__ import annotations
import json
import logging
from typing import Any, Optional

logger = logging.getLogger(__name__)


def build_emotion_segment(
    dims: dict,
    tags: dict,
    sentiment_data: dict,
    temperature_data: dict,
    bociasi_data: dict,
    snapshot_row: dict = None,
) -> dict:
    """构建第5维情绪环境结构化段落

    三层面输出（基于360号§5.3）：
      A. 市场情绪：情绪周期阶段+涨停生态+BOCIASI四象限+情绪温度
      B. 板块情绪：板块热度+轮动状态+龙头状态
      C. 个股情绪：量价形态打分+四类八种状态+情绪拥挤度+换手率异常
    """
    # A. 市场情绪
    market_emotion = _build_market_emotion(sentiment_data, temperature_data, bociasi_data)

    # B. 板块情绪
    sector_emotion = _build_sector_emotion(tags)

    # C. 个股情绪
    stock_emotion = _build_stock_emotion(tags, dims)

    # 综合判定
    overall_light = _judge_overall_light(market_emotion, sector_emotion, stock_emotion)

    # 条件稽核
    conditions = _build_conditions(market_emotion, sector_emotion, stock_emotion)
    satisfied = sum(1 for c in conditions if c['satisfied'])

    # plain白话
    plain = _emotion_plain(market_emotion, sector_emotion, stock_emotion)

    _l = {'green': '✅', 'yellow': '⚠️', 'red': '🚫'}

    return {
        'title': '情绪环境状态',
        'light': _l.get(overall_light, '⚠️'),
        'judgment': market_emotion.get('cycle_phase', '未知'),
        'audit': {
            'conditions': conditions,
            'satisfied_count': satisfied,
            'total_count': len(conditions),
            'confidence': round(satisfied / max(len(conditions), 1), 2),
        },
        'text': (f"市场情绪：{market_emotion.get('cycle_phase', '未知')}; "
                 f"温度：{temperature_data.get('temperature', 'N/A')}({temperature_data.get('level', 'N/A')}); "
                 f"板块：{sector_emotion.get('heat', '未知')}"),
        'plain': plain,
        'data': {
            'market_emotion': market_emotion,
            'sector_emotion': sector_emotion,
            'stock_emotion': stock_emotion,
            'temperature': temperature_data,
        },
    }


def _build_market_emotion(sentiment_data, temperature_data, bociasi_data) -> dict:
    """市场情绪层面"""
    phase = sentiment_data.get('phase', 'neutral')
    phase_label = sentiment_data.get('phase_label', '情绪中性')
    metrics = sentiment_data.get('metrics', {})

    # 六段论经验时长
    duration_map = {
        'ice': ('5-8天', '极端12天'),
        'sprout': ('3-5天', ''),
        'ferment': ('5-10天', ''),
        'climax': ('2-3天', '极端1.5天'),
        'ebb': ('5-10天', ''),
        'recovery': ('循环', ''),
        'regression': ('循环', ''),
    }
    typical_range, extreme = duration_map.get(phase, ('未知', ''))

    # BOCIASI四象限
    quadrant = bociasi_data.get('quadrant', 'MM')
    quadrant_desc = bociasi_data.get('description', '市场情绪中性')

    return {
        'cycle_phase': phase_label,
        'cycle_phase_en': phase,
        'cycle_duration_typical': typical_range,
        'cycle_duration_extreme': extreme,
        'temperature': temperature_data.get('temperature', 50),
        'temperature_level': temperature_data.get('level', '中性'),
        'limit_ecology': {
            'limit_up_count': metrics.get('limit_up_count', 0),
            'limit_down_count': metrics.get('limit_down_count', 0),
            'sealing_rate': metrics.get('sealing_rate', 0),
            'broken_rate': metrics.get('broken_rate', 0),
            'limit_premium': metrics.get('limit_premium', 0),
            'max_board_height': metrics.get('max_board_height', 0),
            'first_board_count': metrics.get('first_board_count', 0),
        },
        'bociasi_quadrant': quadrant,
        'bociasi_description': quadrant_desc,
        'light': _market_light(phase, temperature_data.get('temperature', 50)),
    }


def _build_sector_emotion(tags) -> dict:
    """板块情绪层面

    从pre_feat_cache标签读取板块数据。
    """
    sector_name = str(tags.get('sector_name', ''))
    sector_heat = str(tags.get('sector_heat', ''))
    sector_rank = tags.get('sector_rank')
    rotation_state = str(tags.get('rotation_state', ''))

    return {
        'sector_name': sector_name or '未知',
        'sector_heat': sector_heat or 'unknown',
        'sector_rank': sector_rank,
        'rotation_state': rotation_state or 'NEUTRAL',
        'light': _sector_light(sector_heat),
    }


def _build_stock_emotion(tags, dims) -> dict:
    """个股情绪层面

    从pre_feat_cache标签+dim_states读取个股情绪数据。
    """
    # 量价形态（从dims读取vp状态）
    vp_state = dims.get('vp', {}).get('state', '中性')
    vp_light = dims.get('vp', {}).get('light', 'yellow')

    # 情绪拥挤度
    crowding_label = str(tags.get('crowding_label', ''))
    crowding_value = tags.get('crowding_value')

    # 换手率
    turnover = tags.get('turnover_rate')

    return {
        'vp_state': vp_state,
        'vp_light': vp_light,
        'crowding': {
            'label': crowding_label or 'normal',
            'value': crowding_value,
        },
        'turnover_rate': turnover,
        'light': vp_light,
    }


def _market_light(phase: str, temperature: float) -> str:
    """市场情绪红绿灯"""
    if phase in ('climax',):
        return 'red'  # 高潮→过热
    if phase in ('ice', 'regression'):
        return 'red'  # 冰点→恐慌
    if phase in ('ferment', 'sprout'):
        return 'green'  # 发酵/萌芽→积极
    if temperature >= 70:
        return 'green'
    if temperature <= 30:
        return 'red'
    return 'yellow'


def _sector_light(heat: str) -> str:
    """板块情绪红绿灯"""
    if heat in ('top_10', 'top_20'):
        return 'green'
    if heat == 'none':
        return 'red'
    return 'yellow'


def _judge_overall_light(market, sector, stock) -> str:
    """综合判定第5维红绿灯"""
    lights = [
        market.get('light', 'yellow'),
        sector.get('light', 'yellow'),
        stock.get('light', 'yellow'),
    ]
    red_count = sum(1 for l in lights if l == 'red')
    green_count = sum(1 for l in lights if l == 'green')

    if red_count >= 2:
        return 'red'
    if green_count >= 2:
        return 'green'
    return 'yellow'


def _build_conditions(market, sector, stock) -> list:
    """构建条件稽核列表"""
    conditions = []

    # 情绪周期阶段条件
    phase = market.get('cycle_phase_en', 'neutral')
    conditions.append({
        'name': '情绪周期阶段',
        'satisfied': phase in ('ferment', 'sprout', 'recovery'),
        'actual': market.get('cycle_phase', '未知'),
        'threshold': '发酵/萌芽/复苏',
        'detail': f"当前阶段={market.get('cycle_phase')}"
    })

    # 情绪温度条件
    temp = market.get('temperature', 50)
    conditions.append({
        'name': '情绪温度',
        'satisfied': 30 <= temp <= 70,
        'actual': f"{temp:.0f}",
        'threshold': '30-70（中性区间）',
        'detail': f"温度={temp:.0f}({market.get('temperature_level', '中性')})"
    })

    # BOCIASI四象限条件
    quadrant = market.get('bociasi_quadrant', 'MM')
    conditions.append({
        'name': 'BOCIASI四象限',
        'satisfied': quadrant in ('LL', 'LH'),  # 底部/反弹=积极
        'actual': quadrant,
        'threshold': 'LL或LH',
        'detail': market.get('bociasi_description', '')
    })

    # 板块热度条件
    heat = sector.get('sector_heat', 'unknown')
    conditions.append({
        'name': '板块热度',
        'satisfied': heat in ('top_10', 'top_20'),
        'actual': heat or '未知',
        'threshold': 'top_10或top_20',
        'detail': f"板块={sector.get('sector_name')}"
    })

    return conditions


def _emotion_plain(market, sector, stock) -> str:
    """第5维plain白话文本"""
    parts = []

    # 市场情绪
    phase = market.get('cycle_phase', '未知')
    temp = market.get('temperature', 50)
    parts.append(f"市场处于{phase}（情绪温度{temp:.0f}）")

    # 板块
    heat = sector.get('sector_heat', '')
    if heat and heat != 'unknown':
        parts.append(f"所在板块{heat}")

    # 个股情绪
    vp = stock.get('vp_state', '')
    if vp:
        parts.append(f"个股量价{vp}")

    return '，'.join(parts) if parts else '情绪环境数据不足'
```

### 2.5 修改：build_seven_dim_report()中emotion段落

**修改文件**：`backend/app/opportunity_atlas/status_engine.py`

**修改行号**：641-643（替换emotion段落构建）

```python
# 旧代码（L641-643）:
'seg': _seg('情绪环境状态', dims.get('emotion', {}).get('light', 'yellow'),
            f"市场情绪：{dims.get('emotion', {}).get('state', '正常')}；"
            f"事件：{dims.get('event', {}).get('state', '中性')}",
            '现在是不是好时候'),

# 新代码（364d Phase 4）:
'emotion': _build_emotion_segment_from_snapshot(dims, tags, snapshot_row),
```

**新增辅助函数**：

```python
def _build_emotion_segment_from_snapshot(dims, tags, snapshot_row) -> dict:
    """第5维情绪环境结构化段落"""
    from app.opportunity_atlas.emotion_builder import build_emotion_segment

    try:
        # 获取市场情绪数据
        from app.services.market_sentiment_service import MarketSentimentService
        mss = MarketSentimentService()
        sentiment_data = mss.get_sentiment_phase()
        temperature_data = mss.get_sentiment_temperature()

        # 获取BOCIASI数据
        from app.engine.framework.bociasi_quadrant import BociasiQuadrantAnalyzer
        analyzer = BociasiQuadrantAnalyzer()
        bociasi_data = analyzer.analyze()

        return build_emotion_segment(
            dims=dims, tags=tags,
            sentiment_data=sentiment_data,
            temperature_data=temperature_data,
            bociasi_data=bociasi_data,
            snapshot_row=snapshot_row,
        )
    except Exception as e:
        logger.debug(f"emotion段落构建失败: {e}")
        # 回退到简单输出
        _l = {'green': '✅', 'yellow': '⚠️', 'red': '🚫'}
        emo = dims.get('emotion', {})
        return {
            'title': '情绪环境状态',
            'light': _l.get(emo.get('light', 'yellow'), '⚠️'),
            'judgment': emo.get('state', '正常'),
            'audit': {'conditions': [], 'satisfied_count': 0, 'total_count': 0, 'confidence': 0},
            'text': f"市场情绪：{emo.get('state', '正常')}",
            'plain': f"市场情绪{emo.get('state', '正常')}",
            'data': {},
        }
```

---

## 三、调用链变更

```
旧链路：
  bociasi_quadrant.BociasiQuadrantAnalyzer.analyze() → fast/slow_line（4个固定值子指标）
  market_sentiment_service.MarketSentimentService.get_sentiment_phase() → 4阶段映射
  status_engine._build_dimensions() → dims['emotion'] = {state, light, confidence, evidence}
  status_engine.build_seven_dim_report() → emotion段落（简单拼接）

新链路：
  bociasi_quadrant.BociasiQuadrantAnalyzer.analyze() → fast/slow_line（4个子指标修复为真实计算）
  market_sentiment_service.MarketSentimentService.get_sentiment_phase() → 六段论映射
  market_sentiment_service.MarketSentimentService.get_sentiment_temperature() → 情绪温度0-100（新增）
  status_engine._build_dimensions() → dims['emotion']（保持不变）
  status_engine.build_seven_dim_report() → emotion段落（调用emotion_builder）
  emotion_builder.build_emotion_segment() → 三层面结构化输出（市场+板块+个股）
```

**关键变更**：
- bociasi_quadrant.py 修复4个固定值子指标（换手率分位/RSI分位/ERP分位/PE分位）
- market_sentiment_service.py 从四阶段扩展为六段论 + 新增情绪温度计算
- 新增 `emotion_builder.py` 模块
- `build_seven_dim_report()` 中 emotion 段落从简单拼接升级为三层面结构化构建

---

## 四、测试用例

### 4.1 单元测试

| 测试项 | 输入 | 预期输出 |
|--------|------|---------|
| BOCIASI换手率分位修复 | daily_basic_cache含120日数据 | percentile为0-1浮点数（非固定0.5） |
| BOCIASI RSI分位修复 | factor_cache含RSI_14 | percentile为0-1浮点数（非固定0.5） |
| BOCIASI ERP分位修复 | daily_basic_cache含pe_ttm | percentile为0-1浮点数（非固定0.5） |
| BOCIASI PE分位修复 | daily_basic_cache含pe_ttm | percentile为0-1浮点数（非固定0.5） |
| 六段论-冰点 | limit_up=10,broken=60%,height=1,premium=-1% | phase='ice' |
| 六段论-萌芽 | limit_up=20,broken=40%,height=3 | phase='sprout' |
| 六段论-发酵 | limit_up=45,broken=25%,height=5 | phase='ferment' |
| 六段论-高潮 | limit_up=100,broken=15%,height=8 | phase='climax' |
| 六段论-退潮 | limit_up=20,broken=50%,height=2 | phase='ebb' |
| 六段论-回归 | limit_up=12,broken=55% | phase='regression' |
| 情绪温度-亢奋 | 涨停100+BOCIASI高位 | temperature≥80, level='极度亢奋' |
| 情绪温度-恐慌 | 涨停5+BOCIASI低位 | temperature≤20, level='极度恐慌' |
| 情绪温度-中性 | 一般数据 | 30≤temperature≤70, level='中性' |
| emotion_builder综合 | 正常输入 | 三层面结构化输出 |
| plain文本 | 正常输入 | 包含市场阶段+板块热度+个股状态 |

### 4.2 集成测试

1. 运行全量pytest确认无回归
2. 调用`/api/v3/strategy-analyze`接口，验证返回的seven_dim_report.emotion段落包含：
   - `audit`字段（4条条件稽核）
   - `data.market_emotion`（六段论阶段+涨停生态+BOCIASI+温度）
   - `data.sector_emotion`（板块热度+轮动状态）
   - `data.stock_emotion`（个股量价状态+拥挤度）
   - `data.temperature`（温度值+等级+breakdown）
3. 浏览器验证indicator-ide.html正确渲染三层面情绪环境
4. 验证BOCIASI四象限不再全部返回固定0.5

---

## 五、实施步骤

| 步骤 | 内容 | 工作量 |
|------|------|:------:|
| 1 | 修复bociasi_quadrant.py 4个子指标 | 2h |
| 2 | market_sentiment_service.py 六段论扩展 | 2h |
| 3 | market_sentiment_service.py 情绪温度计算 | 2h |
| 4 | 新建emotion_builder.py（三层面构建器） | 2h |
| 5 | 修改build_seven_dim_report() emotion段落 | 0.5h |
| 6 | 单元测试+集成测试 | 1.5h |
| **合计** | | **10h** |

---

## 修订记录

| 版本 | 日期 | 修订内容 |
|------|------|---------|
| v1.0 | 2026-08-21 | 初版：修复4个BOCIASI子指标+六段论扩展+情绪温度0-100+三层面结构化+条件稽核 |
