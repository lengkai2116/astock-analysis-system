"""
板块分析服务（288号方案 v1.1）
封装行业数据获取、排名计算、轮动判断，供五维卡4和后续所有板块需求共用
"""
from datetime import datetime

import logging
logger = logging.getLogger(__name__)


class SectorAnalysisService:
    """板块分析服务"""

    def get_sector_context(self, ts_code: str) -> dict:
        """获取单只股票的完整板块上下文"""
        from app.data import DataManager
        dm = DataManager()

        industry_name = dm.get_industry_for_stock(ts_code)
        if not industry_name:
            return {'sector_name': '', 'available': False}

        idx_df = dm.get_industry_index_data(industry_name)
        if idx_df is None or idx_df.empty:
            return {
                'sector_name': industry_name,
                'available': False,
                'message': f'行业指数数据未就绪: {industry_name}',
            }

        closes = idx_df['close'].values
        ret_1d = float(idx_df.iloc[-1].get('pct_chg', 0)) if 'pct_chg' in idx_df.columns else 0.0
        ret_5d = float((closes[-1] / closes[-6] - 1) * 100) if len(closes) >= 6 else 0.0
        ret_20d = float((closes[-1] / closes[-21] - 1) * 100) if len(closes) >= 21 else 0.0

        # 个股收益率（用于超额收益计算）
        stock_df = dm.get_cached_daily_data(ts_code)
        stock_ret_1d = 0.0
        stock_ret_20d = 0.0
        if stock_df is not None and not stock_df.empty:
            s_close = stock_df['close'].values
            stock_ret_1d = float(stock_df.iloc[-1].get('pct_chg', 0)) if 'pct_chg' in stock_df.columns else 0.0
            stock_ret_20d = float((s_close[-1] / s_close[-21] - 1) * 100) if len(s_close) >= 21 else 0.0

        # 行业排名
        rankings = dm.get_all_industry_rankings()
        rank_1d = next((r['rank'] for r in rankings if r['name'] == industry_name), 0)

        # 轮动状态
        rotation_state = self._calc_rotation_state(ret_20d, ret_5d)

        # 板块资金流向
        moneyflow = self._get_sector_moneyflow_rank(dm, industry_name)

        # 板块内涨幅前3
        top_stocks = self._get_top_stocks_in_sector(dm, industry_name)

        return {
            'sector_name': industry_name,
            'available': True,
            'sector_daily_return': round(ret_1d, 2),
            'sector_5d_return': round(ret_5d, 2),
            'sector_20d_return': round(ret_20d, 2),
            'sector_rank_1d': rank_1d,
            'excess_return_1d': round(stock_ret_1d - ret_1d, 2),
            'excess_return_20d': round(stock_ret_20d - ret_20d, 2),
            'rotation_state': rotation_state,
            'sector_moneyflow_rank': moneyflow.get('rank', 0),
            'sector_moneyflow_net': moneyflow.get('net_amount', 0),
            'top_stocks': top_stocks[:3],
        }

    def _calc_rotation_state(self, ret_20d: float, ret_5d: float) -> str:
        """板块轮动状态判断（内联版）
        
        按极端程度从高到低判断：LAGGING(-10%↓) → LEADING(+10%↑) → WEAKENING → STRENGTHENING → NEUTRAL
        """
        if ret_20d < -10:
            return 'LAGGING'
        elif ret_20d > 10:
            return 'LEADING'
        elif ret_20d < -5 and ret_5d < 0:
            return 'WEAKENING'
        elif ret_20d > 5 and ret_5d > 0:
            return 'STRENGTHENING'
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
            from app.data.enhanced_cache_manager import get_ecm_instance
            ecm = get_ecm_instance()
            today = datetime.now().strftime('%Y%m%d')
            rows = ecm._fetchall(
                """SELECT s.ts_code, s.name, d.pct_chg FROM stocks s
                   JOIN daily_cache d ON s.ts_code = d.ts_code AND d.trade_date = ?
                   WHERE s.industry = ? AND d.pct_chg IS NOT NULL
                   ORDER BY d.pct_chg DESC LIMIT ?""",
                [today, industry_name, top_n]
            )
            return [
                {'ts_code': r[0], 'name': r[1], 'pct_chg': float(r[2]) if r[2] else 0}
                for r in rows
            ]
        except Exception:
            return []
