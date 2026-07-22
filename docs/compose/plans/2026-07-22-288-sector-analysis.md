# 板块策略分析 Implementation Plan（v1.1 精炼版）

**Goal:** 补齐申万行业指数日线数据底座，通过 SectorAnalysisService 封装板块分析逻辑，合入 E12 响应

**Architecture:**
- daemon 扩展 `_batch_sw_index_daily` 采集 31 个申万行业指数日线 → `daily_cache`
- SectorAnalysisService 封装全部板块分析逻辑（排名/轮动/超额收益）
- E12 响应直接嵌入板块增强字段，不新增独立 API 端点
- SectorRotationModel 保留不动（内联逻辑不进它）

---

### Task 1: 数据底座

**Files:**
- Modify: `backend/data_daemon.py`
- Modify: `backend/app/data/__init__.py`
- Modify: `backend/app/data/enhanced_cache_manager.py`

- [ ] **Step 1: 前置验证 — 确认 Stock.industry 真实值分布**

```bash
# 连接 SQLite 数据库执行
python -c "
import sqlite3
conn = sqlite3.connect('data/stock_cache.db')
rows = conn.execute('SELECT DISTINCT industry FROM stocks WHERE industry IS NOT NULL AND industry != \"\" ORDER BY industry').fetchall()
for r in rows:
    print(r[0])
print(f'Total distinct industries: {len(rows)}')
"
```

如果值 = 申万一级行业名（31个左右）→ 用附录 B 的 `INDUSTRY_TO_CODE` 映射
如果值 = 子行业名（100+）→ 用 `SUB_INDUSTRY_TO_CODE` 多对一映射
如果不匹配 → 切换 AKShare 方案 B

- [ ] **Step 2: daemon 新增申万行业指数采集 + 60日回填**

```python
# In data_daemon.py, add after the major index collection:

SW_INDEX_CODES = [
    '801010.SI', '801020.SI', '801030.SI', '801040.SI', '801050.SI',
    '801080.SI', '801110.SI', '801120.SI', '801130.SI', '801140.SI',
    '801150.SI', '801160.SI', '801170.SI', '801180.SI', '801200.SI',
    '801210.SI', '801230.SI', '801710.SI', '801720.SI', '801730.SI',
    '801740.SI', '801750.SI', '801760.SI', '801770.SI', '801780.SI',
    '801790.SI', '801880.SI', '801890.SI',
]

def _batch_sw_index_daily(trade_date=None):
    """采集申万一级行业指数日线"""
    _ensure_pd()
    if trade_date is None:
        trade_date = datetime.now().strftime('%Y%m%d')
    try:
        from app.data.tushare_provider import TushareProvider
        pro = TushareProvider()
        collected = 0
        for code in SW_INDEX_CODES:
            try:
                # 当日数据
                df = pro.daily(ts_code=code, start_date=trade_date, end_date=trade_date)
                if df is not None and not df.empty:
                    _ecm.cache_daily_data(df)
                    collected += 1
            except Exception:
                continue
        logger.info(f"申万行业指数采集完成: {collected}/{len(SW_INDEX_CODES)}")
    except Exception as e:
        logger.warning(f"申万行业指数采集失败: {e}")

def _backfill_sw_index(backfill_days=60):
    """首次/巡检时回填历史行业指数数据"""
    _ensure_pd()
    start = (datetime.now() - timedelta(days=backfill_days)).strftime('%Y%m%d')
    end = datetime.now().strftime('%Y%m%d')
    try:
        from app.data.tushare_provider import TushareProvider
        pro = TushareProvider()
        for code in SW_INDEX_CODES:
            try:
                df = pro.daily(ts_code=code, start_date=start, end_date=end)
                if df is not None and not df.empty:
                    _ecm.cache_daily_data(df)
            except Exception:
                continue
        logger.info(f"申万行业指数历史数据回填完成（{backfill_days}天）")
    except Exception as e:
        logger.warning(f"申万行业指数回填失败: {e}")
```

在 `run_daily_sync()` 中插入：
```python
_batch_sw_index_daily(trade_date)
```

在 `run_integrity_check()` 中扩展：
```python
# 检查行业指数完整性
count = _ecm.conn.execute(
    "SELECT COUNT(DISTINCT ts_code) FROM daily_cache WHERE ts_code LIKE '801%.SI'"
).fetchone()[0]
if count < 31:
    _backfill_sw_index()
```

- [ ] **Step 3: DataManager 新增行业指数读取方法**

```python
# In backend/app/data/__init__.py

# 依据前置验证结果选择映射表
INDUSTRY_TO_CODE = {
    '农林牧渔': '801010.SI', '采掘': '801020.SI',
    '化工': '801030.SI', '钢铁': '801040.SI',
    '有色金属': '801050.SI', '电子': '801080.SI',
    '家用电器': '801110.SI', '食品饮料': '801120.SI',
    '纺织服装': '801130.SI', '轻工制造': '801140.SI',
    '医药生物': '801150.SI', '公用事业': '801160.SI',
    '交通运输': '801170.SI', '房地产': '801180.SI',
    '商业贸易': '801200.SI', '休闲服务': '801210.SI',
    '综合': '801230.SI', '建筑材料': '801710.SI',
    '建筑装饰': '801720.SI', '电气设备': '801730.SI',
    '国防军工': '801740.SI', '计算机': '801750.SI',
    '传媒': '801760.SI', '通信': '801770.SI',
    '银行': '801780.SI', '非银金融': '801790.SI',
    '汽车': '801880.SI', '机械设备': '801890.SI',
}

def get_industry_index_data(self, industry_name: str) -> pd.DataFrame | None:
    """获取行业指数日线数据"""
    code = INDUSTRY_TO_CODE.get(industry_name)
    if not code:
        return None
    return self.get_cached_daily_data(code)

def get_all_industry_rankings(self) -> list[dict]:
    """获取所有行业当日涨跌幅排名"""
    rankings = []
    today = datetime.now().strftime('%Y%m%d')
    for ind_name, code in INDUSTRY_TO_CODE.items():
        df = self.get_industry_index_data(ind_name)
        if df is not None and not df.empty:
            latest = df.iloc[-1]
            pct = float(latest.get('pct_chg', 0))
            rankings.append({'name': ind_name, 'code': code, 'pct': pct})
    rankings.sort(key=lambda x: x['pct'], reverse=True)
    for i, r in enumerate(rankings, 1):
        r['rank'] = i
    return rankings

def get_industry_for_stock(self, ts_code: str) -> str | None:
    """获取个股所属行业"""
    try:
        row = self.cache._fetchone(
            "SELECT industry FROM stocks WHERE ts_code=?", [ts_code]
        )
        return row[0] if row else None
    except Exception:
        return None
```

- [ ] **Step 4: ECM 附带归档修复**

```python
# In enhanced_cache_manager.py

def read_as_sector_ranking(self) -> list[dict]:
    try:
        rows = self._fetchall("SELECT * FROM as_sector_ranking ORDER BY change_pct DESC")
        if rows:
            cols = ['sector_name', 'ts_code', 'change_pct', 'up_count', 'down_count',
                    'lead_ts_code', 'lead_name', 'lead_change_pct', 'updated_at']
            return [dict(zip(cols, r)) for r in rows]
    except Exception:
        pass
    return []

def read_as_concept_ranking(self) -> list[dict]:
    try:
        rows = self._fetchall("SELECT * FROM as_concept_ranking ORDER BY change_pct DESC")
        if rows:
            cols = ['concept_name', 'ts_code', 'change_pct', 'up_count', 'down_count', 'updated_at']
            return [dict(zip(cols, r)) for r in rows]
    except Exception:
        pass
    return []
```

---

### Task 2: SectorAnalysisService + 五维卡4修复

**Files:**
- Create: `backend/app/services/sector_analysis_service.py`
- Modify: `backend/app/routes/strategy_analyze.py`

- [ ] **Step 1: 新建 SectorAnalysisService**

```python
# backend/app/services/sector_analysis_service.py

import logging
from datetime import datetime
from typing import Optional

logger = logging.getLogger(__name__)

class SectorAnalysisService:
    """板块分析服务——封装行业数据获取、排名计算、轮动判断"""

    def get_sector_context(self, ts_code: str) -> dict:
        """获取单只股票的完整板块上下文"""
        from app.data import DataManager
        dm = DataManager()

        # 获取行业名
        industry_name = dm.get_industry_for_stock(ts_code)
        if not industry_name:
            return {'sector_name': '', 'sector_index_code': '', 'available': False}

        # 获取行业指数数据
        idx_df = dm.get_industry_index_data(industry_name)
        if idx_df is None or idx_df.empty:
            return {'sector_name': industry_name, 'available': False,
                    'message': f'行业指数数据未就绪: {industry_name}'}

        closes = idx_df['close'].values
        ret_1d = float(idx_df.iloc[-1].get('pct_chg', 0)) if 'pct_chg' in idx_df.columns else 0
        ret_5d = float((closes[-1] / closes[-6] - 1) * 100) if len(closes) >= 6 else 0
        ret_20d = float((closes[-1] / closes[-21] - 1) * 100) if len(closes) >= 21 else 0

        # 个股收益率（用于超额收益计算）
        stock_df = dm.get_cached_daily_data(ts_code)
        stock_ret_1d = 0.0
        stock_ret_20d = 0.0
        if stock_df is not None and not stock_df.empty:
            s_close = stock_df['close'].values
            stock_ret_1d = float(stock_df.iloc[-1].get('pct_chg', 0)) if 'pct_chg' in stock_df.columns else 0
            stock_ret_20d = float((s_close[-1] / s_close[-21] - 1) * 100) if len(s_close) >= 21 else 0

        # 获取行业排名
        rankings = dm.get_all_industry_rankings()
        rank_1d = next((r['rank'] for r in rankings if r['name'] == industry_name), 0)

        # 轮动状态判断（内联版，不依赖原 SectorRotationModel）
        rotation_state = self._calc_rotation_state(ret_20d, ret_5d)

        # 板块资金流向排名
        moneyflow = self._get_sector_moneyflow_rank(dm, industry_name)

        # 板块内涨幅前3个股
        top_stocks = self._get_top_stocks_in_sector(dm, industry_name)

        return {
            'sector_name': industry_name,
            'available': True,
            'sector_index_code': '',  # 由调用方从映射表获取
            'sector_daily_return': round(ret_1d, 2),
            'sector_5d_return': round(ret_5d, 2),
            'sector_20d_return': round(ret_20d, 2),
            'sector_rank_1d': rank_1d,
            'sector_rank_5d': 0,  # 简化版暂不实现5日排名
            'excess_return_1d': round(stock_ret_1d - ret_1d, 2),
            'excess_return_20d': round(stock_ret_20d - ret_20d, 2),
            'rotation_state': rotation_state,
            'sector_moneyflow_rank': moneyflow.get('rank', 0),
            'sector_moneyflow_net': moneyflow.get('net_amount', 0),
            'top_stocks': top_stocks[:3],
        }

    def _calc_rotation_state(self, ret_20d: float, ret_5d: float) -> str:
        """计算板块轮动状态"""
        if ret_20d > 10:
            return 'LEADING'
        elif ret_20d > 5 and ret_5d > 0:
            return 'STRENGTHENING'
        elif ret_20d < -5 and ret_5d < 0:
            return 'WEAKENING'
        elif ret_20d < -10:
            return 'LAGGING'
        else:
            return 'NEUTRAL'

    def _get_sector_moneyflow_rank(self, dm, industry_name: str) -> dict:
        """获取板块资金流向排名"""
        try:
            from app.services.dashboard_service import DashboardService
            svc = DashboardService()
            sectors = svc.get_sector_moneyflow(top_n=31, stocks_per_sector=1)
            for i, s in enumerate(sectors, 1):
                if s.get('sector_name') == industry_name:
                    return {'rank': i, 'net_amount': s.get('net_amount', 0)}
        except Exception:
            pass
        return {'rank': 0, 'net_amount': 0}

    def _get_top_stocks_in_sector(self, dm, industry_name: str, top_n: int = 3) -> list[dict]:
        """获取板块内涨幅前 N 的个股"""
        try:
            from app.data import DataManager
            dm = DataManager()
            today = datetime.now().strftime('%Y%m%d')
            stocks = dm.get_cached_daily_data(None)  # placeholder
            # 实际查询通过 ECM 直接 SQL
            from app.data.enhanced_cache_manager import get_ecm_instance
            ecm = get_ecm_instance()
            rows = ecm._fetchall(
                """SELECT s.ts_code, s.name, d.pct_chg FROM stocks s
                   JOIN daily_cache d ON s.ts_code = d.ts_code AND d.trade_date = ?
                   WHERE s.industry = ? AND d.pct_chg IS NOT NULL
                   ORDER BY d.pct_chg DESC LIMIT ?""",
                [today, industry_name, top_n]
            )
            return [{'ts_code': r[0], 'name': r[1], 'pct_chg': float(r[2]) if r[2] else 0}
                    for r in rows]
        except Exception:
            return []
```

- [ ] **Step 2: 修改 E12 的 emotion 维度**

在 `strategy_analyze.py` 的 `_build_signal_context()` 中：

```python
def _build_signal_context(ts_code: str) -> Dict:
    """构建信号上下文（含真实板块数据）"""
    ctx = {'ts_code': ts_code}

    # 从 SectorAnalysisService 获取板块数据
    try:
        from app.services.sector_analysis_service import SectorAnalysisService
        sas = SectorAnalysisService()
        sector_ctx = sas.get_sector_context(ts_code)
        if sector_ctx.get('available'):
            ctx['sector_name'] = sector_ctx['sector_name']
            ctx['sector_pct'] = sector_ctx['sector_daily_return']  # ← 真实板块涨跌幅
            ctx['sector_rank_1d'] = sector_ctx['sector_rank_1d']
            ctx['excess_return_1d'] = sector_ctx['excess_return_1d']
            ctx['excess_return_20d'] = sector_ctx['excess_return_20d']
            ctx['rotation_state'] = sector_ctx['rotation_state']
            ctx['sector_moneyflow_rank'] = sector_ctx['sector_moneyflow_rank']
            return ctx
    except Exception as e:
        logger.debug(f"SectorAnalysisService 不可用: {e}")

    # fallback: Stock.industry + daily_basic
    from app.data import DataManager
    dm = DataManager()
    stk = dm.get_stock_info(ts_code)
    if stk and stk.get('industry'):
        ctx['sector_name'] = stk['industry']
    df_basic = dm.get_cached_daily_basic(ts_code)
    if df_basic is not None and not df_basic.empty:
        ctx['sector_pct'] = float(df_basic.iloc[-1].get('pct_chg', 0))
    return ctx
```

在 `_build_emotion_dimension()` 中，新增传递给前端的板块增强字段：

```python
def _build_emotion_dimension(sig, signal_context=None) -> Dict:
    result = {
        # ... 原有字段不变 ...
        'sector': signal_context.get('sector_name', '未知'),
        'sector_pct': signal_context.get('sector_pct', 0),
    }
    # 新增板块增强字段
    if 'sector_rank_1d' in (signal_context or {}):
        result['sector_rank_1d'] = signal_context['sector_rank_1d']
        result['excess_return_1d'] = signal_context.get('excess_return_1d', 0)
        result['excess_return_20d'] = signal_context.get('excess_return_20d', 0)
        result['rotation_state'] = signal_context.get('rotation_state', 'UNKNOWN')
    return result
```

---

### Task 3: 选股板块过滤（可选）

**Files:**
- Modify: `backend/app/engine/framework/screener_strategy_integration.py`

实现在 288 方案 §四 改动 5 中已有详细描述，此处略。

---

### Verification

```bash
# 1. 行业指数采集验证
python -c "
from app.data import DataManager
dm = DataManager()
df = dm.get_cached_daily_data('801120.SI')
print(f'食品饮料指数数据: {len(df)} 行' if df is not None else '无数据')
rankings = dm.get_all_industry_rankings()
print(f'行业排名: {len(rankings)} 个行业')
for r in rankings[:3]:
    print(f'  #{r[\"rank\"]} {r[\"name\"]}: {r[\"pct\"]}%')
"

# 2. SectorAnalysisService 验证
python -c "
from app.services.sector_analysis_service import SectorAnalysisService
sas = SectorAnalysisService()
ctx = sas.get_sector_context('000001.SZ')
print(f'板块上下文: {ctx[\"sector_name\"]} 轮动={ctx[\"rotation_state\"]} 涨跌幅={ctx[\"sector_daily_return\"]}%')
"
```
