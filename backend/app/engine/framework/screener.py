"""
多层股票筛选系统
参考 LEAN 的三层筛选架构

方案G版本 (2026-06-02):
  ST/退市 → 换手率<1% → PE>300(金融豁免) → 亏损微盘(PE=0&市值<30亿&换手<3%)
  数据驱动校准: 24.8%剔除率 / 5506只实测
"""
from typing import Dict, List, Optional, Any
from datetime import datetime
import pandas as pd
import numpy as np
import requests
from functools import lru_cache
import os
from dotenv import load_dotenv

from . import UniverseSelectionModel, Algorithm
from .chip_strategy import ChipUniverseSelectionModel, ChipScorer


# ── Tushare Pro API 辅助函数 ──
@lru_cache(maxsize=1)
def _get_tushare_token() -> Optional[str]:
    load_dotenv()
    load_dotenv(os.path.join(os.path.dirname(__file__), '..', '..', '..', '.env.local'))
    return os.getenv('TUSHARE_TOKEN')


def _tushare_pro(api_name: str, params: dict, fields: str) -> Optional[dict]:
    token = _get_tushare_token()
    if not token:
        return None
    try:
        resp = requests.post('http://api.tushare.pro', json={
            'api_name': api_name, 'token': token,
            'params': params, 'fields': fields
        }, timeout=10)
        data = resp.json()
        if data.get('code') == 0 and data.get('data', {}).get('items'):
            return data['data']
    except Exception:
        pass
    return None


@lru_cache(maxsize=2048)
def _fetch_stock_name(symbol: str) -> Optional[str]:
    result = _tushare_pro('stock_basic',
        {'ts_code': symbol, 'list_status': ''},
        'ts_code,name')
    if result and result['items']:
        for item in result['items']:
            if item[0] == symbol:
                return str(item[1])
    return None


@lru_cache(maxsize=2048)
def _is_st_stock(symbol: str) -> Optional[bool]:
    name = _fetch_stock_name(symbol)
    if name:
        return '*ST' in name or 'ST' in name or '退市' in name or 'SST' in name
    return None

import logging
logger = logging.getLogger(__name__)

# 金融行业白名单（PE_TTM=0 时豁免）
FINANCIAL_SECTORS = {"银行", "保险", "证券", "多元金融"}


class DarwinRiskFilter:
    """
    达尔文风险过滤 - 第一层筛选
    负责剔除高风险股票

    过滤链（方案G，按顺序）:
      1. _filter_st:           名称含 ST/退市 → 一票否决
      2. _filter_low_liquidity: 20日均换手率<1% 或 成交额<1000万 → 一票否决
      3. _filter_high_valuation: PE_TTM>300（金融豁免）→ 一票否决
      4. _filter_continuous_loss: PE=0 + 流通市值<30亿 + 换手<3% → 一票否决
    """

    def __init__(self, data_manager: Optional['DataManager'] = None):
        self.filter_rules = [
            self._filter_st,
            self._filter_low_liquidity,
            self._filter_high_valuation,
            self._filter_continuous_loss,
        ]
        self._data_manager = data_manager
        self._stock_info_cache = {}
        self._industry_cache = {}

    @property
    def data_manager(self):
        if self._data_manager is None:
            from app.data import DataManager
            self._data_manager = DataManager()
        return self._data_manager

    def filter(self, stock_list: List[str], stock_data: Dict[str, pd.DataFrame]) -> List[str]:
        """
        应用风险过滤

        Args:
            stock_list: 股票代码列表
            stock_data: 股票数据 {symbol: DataFrame}

        Returns:
            通过过滤的股票列表
        """
        passed = []

        for symbol in stock_list:
            data = stock_data.get(symbol, pd.DataFrame())

            if self._apply_filters(symbol, data):
                passed.append(symbol)

        return passed

    def _apply_filters(self, symbol: str, data: pd.DataFrame) -> bool:
        """应用所有过滤规则"""
        for rule in self.filter_rules:
            if not rule(symbol, data):
                return False
        return True

    # ── 规则1: ST/退市 → 名称过滤 ──
    def _filter_st(self, symbol: str, data: pd.DataFrame) -> bool:
        """过滤ST/退市股票 - 基于股票名称"""
        # 1. 优先从数据库 Stock 表查询（精准）
        try:
            from app.models import Stock
            stock = Stock.query.get(symbol)
            if stock and stock.name:
                name = stock.name
                if '*ST' in name or 'ST' in name or '退市' in name or 'SST' in name:
                    return False
                return True  # 数据库查到名称且非ST，直接通过
        except Exception:
            pass

        # 2. 回退到 stock_list 缓存查询
        name = self._get_stock_name(symbol)
        if name:
            if '*ST' in name or 'ST' in name or '退市' in name or 'SST' in name:
                return False
            return True  # 缓存查到名称且非ST

        # 3. Tushare API 直接查询
        try:
            is_st = _is_st_stock(symbol)
            if is_st is not None:
                return not is_st  # ST→False(剔除), 非ST→True(通过)
        except Exception:
            pass

        # 4. 以上均不可用：默认通过
        return True

    # ── 规则2: 低流动性 → 换手率<1% 或 成交额<1000万 ──
    def _filter_low_liquidity(self, symbol: str, data: pd.DataFrame) -> bool:
        """过滤低流动性股票 - 换手率<1% 或 成交额<1000万"""
        if data.empty or len(data) < 20:
            return False

        # 成交额检查（防数据缺失时最低保障）
        if 'amount' in data.columns:
            avg_amount = data['amount'].tail(20).mean()
            if avg_amount < 10000000:  # 日均成交额 < 1000万
                return False
        elif 'vol' in data.columns:
            avg_vol = data['vol'].tail(20).mean()
            if avg_vol < 500000:
                return False

        # 换手率检查（方案G: 阈值 1%）
        turnover_checked = False
        try:
            basic_df = self.data_manager.get_cached_daily_basic(
                symbol,
                start_date=(datetime.now() - pd.Timedelta(days=60)).strftime('%Y-%m-%d')
            )
            if not basic_df.empty and 'turnover_rate' in basic_df.columns:
                tr_series = basic_df['turnover_rate'].dropna().tail(20)
                if len(tr_series) > 0:
                    avg_tr = float(tr_series.mean())
                    if avg_tr < 1.0:  # 20日均换手率<1% 排除
                        return False
                    turnover_checked = True
        except Exception:
            pass
        
        # Tushare API 回退（缓存为空时）
        if not turnover_checked:
            try:
                today = datetime.now().strftime('%Y%m%d')
                start = (datetime.now() - pd.Timedelta(days=60)).strftime('%Y%m%d')
                result = _tushare_pro('daily_basic',
                    {'ts_code': symbol, 'start_date': start, 'end_date': today},
                    'trade_date,turnover_rate')
                if result and result['items']:
                    fields = result['fields']
                    tr_idx = fields.index('turnover_rate')
                    tr_values = [float(item[tr_idx]) for item in result['items']
                                 if item[tr_idx] is not None]
                    if len(tr_values) >= 5:
                        avg_tr = sum(tr_values[-20:]) / min(len(tr_values[-20:]), 20)
                        if avg_tr < 1.0:
                            return False
            except Exception:
                pass

        return True

    # ── 规则3: 极高估值 → PE_TTM>300（金融行业豁免）──
    def _filter_high_valuation(self, symbol: str, data: pd.DataFrame) -> bool:
        """过滤高估值股票 - PE_TTM>300（金融行业除外）"""
        try:
            basic_df = self.data_manager.get_cached_daily_basic(
                symbol,
                start_date=(datetime.now() - pd.Timedelta(days=30)).strftime('%Y-%m-%d')
            )
            if not basic_df.empty and 'pe_ttm' in basic_df.columns:
                pe_series = basic_df['pe_ttm'].dropna()
                if len(pe_series) > 0:
                    latest_pe = float(pe_series.iloc[-1])
                    if latest_pe > 300:  # 阈值300，保护成长股
                        industry = self._get_stock_industry(symbol)
                        if industry not in FINANCIAL_SECTORS:
                            return False
        except Exception:
            pass

        return True

    # ── 规则4: 亏损微盘 → PE=0 + 市值<30亿 + 换手<3% ──
    def _filter_continuous_loss(self, symbol: str, data: pd.DataFrame) -> bool:
        """
        过滤亏损微盘股（三重条件防误杀）

        仅当同时满足以下条件时才剔除:
          - PE_TTM = 0（Tushare亏损标记）
          - 流通市值 < 30亿元（小盘）
          - 20日均换手率 < 3%（低流动性）

        金融行业豁免（银行PE常为0）。
        """
        try:
            basic_df = self.data_manager.get_cached_daily_basic(
                symbol,
                start_date=(datetime.now() - pd.Timedelta(days=60)).strftime('%Y-%m-%d')
            )
            if basic_df.empty:
                return True  # 无数据时默认通过

            latest = basic_df.iloc[-1]

            # PE_TTM = 0 → 亏损标记
            pe_ttm = latest.get('pe_ttm')
            if pd.isna(pe_ttm) or float(pe_ttm) != 0.0:
                return True  # PE正常，不适用此规则

            # 金融行业豁免
            industry = self._get_stock_industry(symbol)
            if industry in FINANCIAL_SECTORS:
                return True

            # 流通市值 < 30亿（circ_mv 单位为万元）
            circ_mv = latest.get('circ_mv')
            if pd.isna(circ_mv) or float(circ_mv) >= 300000:
                return True  # 市值>=30亿，不剔除

            # 20日均换手率 < 3%
            if 'turnover_rate' in basic_df.columns:
                tr_series = basic_df['turnover_rate'].dropna().tail(20)
                if len(tr_series) > 0:
                    avg_tr = float(tr_series.mean())
                    if avg_tr < 3.0:
                        return False  # 三重条件全部满足 → 剔除
        except Exception:
            pass

        return True

    # ── 辅助方法 ──
    def _get_stock_name(self, symbol: str) -> Optional[str]:
        """获取股票名称（缓存）"""
        if symbol in self._stock_info_cache:
            return self._stock_info_cache[symbol]

        try:
            stock_list = self.data_manager.get_stock_list()
            for s in stock_list:
                if s.get('ts_code') == symbol:
                    name = s.get('name', '')
                    if name:
                        self._stock_info_cache[symbol] = name
                        return name
        except Exception:
            pass

        # 3. Tushare API 回退
        try:
            name = _fetch_stock_name(symbol)
            if name:
                self._stock_info_cache[symbol] = name
                return name
        except Exception:
            pass

        return None

    def _get_stock_industry(self, symbol: str) -> str:
        """获取股票行业（缓存）"""
        if symbol in self._industry_cache:
            return self._industry_cache[symbol]

        # 1. 优先从 Stock ORM 获取
        try:
            from app.models import Stock
            stock = Stock.query.get(symbol)
            if stock and stock.industry:
                self._industry_cache[symbol] = stock.industry
                return stock.industry
        except Exception:
            pass

        # 2. 回退到 stock_list 查询
        try:
            stock_list = self.data_manager.get_stock_list()
            for s in stock_list:
                if s.get('ts_code') == symbol:
                    ind = s.get('industry', '')
                    if ind:
                        self._industry_cache[symbol] = ind
                        return ind
        except Exception:
            pass

        return ''


class MultiLayerStockScreener:
    """
    多层股票筛选器
    整合三层筛选架构
    """

    def __init__(self):
        self.layer1 = DarwinRiskFilter()
        self.layer2_scorer = ChipScorer()

    def screen(self, all_stocks: List[str], stock_data: Dict[str, pd.DataFrame]) -> List[Dict]:
        """
        执行多层筛选

        Args:
            all_stocks: 全市场股票列表
            stock_data: 股票数据 {symbol: DataFrame}

        Returns:
            筛选结果列表，按评分排序
        """
        logger.info(f"开始第一层筛选: 风险过滤...")
        layer1_results = self.layer1.filter(all_stocks, stock_data)
        logger.info(f"第一层通过: {len(layer1_results)} 只股票")

        logger.info(f"开始第二层筛选: 主力资金识别...")
        layer2_results = []
        for symbol in layer1_results:
            try:
                data = stock_data.get(symbol, pd.DataFrame())
                if data.empty:
                    continue

                score = self.layer2_scorer.score(data)
                if score > 0:
                    layer2_results.append({
                        'symbol': symbol,
                        'score': score
                    })

            except Exception as e:
                logger.error(f"处理股票 {symbol} 时出错: {e}")

        # 按评分排序
        layer2_results.sort(key=lambda x: x['score'], reverse=True)
        layer2_results = layer2_results[:100]  # 取前100只
        logger.info(f"第二层通过: {len(layer2_results)} 只股票")

        logger.info(f"开始第三层筛选: 多策略验证...")
        layer3_results = self._apply_strategy_validation(layer2_results, stock_data)
        logger.info(f"第三层通过: {len(layer3_results)} 只股票")

        return layer3_results

    def _apply_strategy_validation(self, candidates: List[Dict], stock_data: Dict[str, pd.DataFrame]) -> List[Dict]:
        """
        第三层: 策略验证（简化实现）
        实际可以添加更多策略验证
        """
        validated = []

        for candidate in candidates:
            symbol = candidate['symbol']
            data = stock_data.get(symbol, pd.DataFrame())

            if data.empty:
                continue

            # 简单的验证逻辑
            if len(data) >= 60:
                candidate['validated'] = True
                candidate['data_points'] = len(data)
                validated.append(candidate)

        return validated


class SignalFusion:
    """
    多策略信号融合器
    """

    def __init__(self, strategy_weights: Optional[Dict[str, float]] = None):
        """
        Args:
            strategy_weights: 策略权重配置
        """
        self.weights = strategy_weights or {
            'chip': 0.30,
            'chanlun': 0.25,
            'factor': 0.20,
            'volume_price': 0.25,
        }

    def fuse(self, signals_dict: Dict[str, float]) -> Dict:
        """
        融合多策略信号

        Args:
            signals_dict: 各策略信号 {strategy_name: signal_value}
                         signal_value: -1=卖, 0=观望, 1=买

        Returns:
            融合后的信号结果
        """
        total_weight = sum(w for s, w in self.weights.items() if s in signals_dict)

        if total_weight <= 0:
            return {
                'action': 'HOLD',
                'confidence': 0.0,
                'details': signals_dict
            }

        fused_score = 0.0
        for strategy, weight in self.weights.items():
            if strategy in signals_dict:
                normalized_weight = weight / total_weight
                fused_score += signals_dict[strategy] * normalized_weight

        if fused_score > 0.3:
            action = 'BUY'
        elif fused_score < -0.3:
            action = 'SELL'
        else:
            action = 'HOLD'

        confidence = min(0.9, abs(fused_score) * 0.5 + 0.1)

        return {
            'action': action,
            'score': fused_score,
            'confidence': confidence,
            'details': signals_dict
        }
