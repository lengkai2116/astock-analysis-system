"""事件监控器 — 20 类事件检测、评分合并、新闻质量过滤、仓位联动

5 维度 20 类事件覆盖:
  A 财务事件 (A1-A5)
  B 资本运作 (B1-B6)
  C 监管事件 (C1-C3)
  D 市场情绪 (D1-D4)
  E 特殊事件 (E1-E2)

设计原则:
  - DataManager 延迟导入，单个事件失败不影响其他事件
  - 数据不存在时（ECM 表为空）返回 detected=False，不阻断流程
  - 遵循四层架构红线：不实例化数据源 Provider
"""

from __future__ import annotations

import logging
from datetime import date, datetime
from typing import Any

import numpy as np
import pandas as pd

from app.data.mixins import DataAwareMixin

logger = logging.getLogger(__name__)

# ── 仓位联动映射 ──────────────────────────────────────────
MAX_POSITION_RATIO: dict[int, float] = {
    5: 0.8, 4: 0.8, 3: 0.8, 2: 0.6, 1: 0.6,
    0: 0.4,
    -1: 0.2, -2: 0.2, -3: 0.0, -4: 0.0, -5: 0.0,
}

# ── catalyst 映射（取绝对值最大的事件类型 → 295号§3.4 十类枚举） ──────────────
CATALYST_EVENT_MAP: dict[str, str] = {
    'earnings_surprise': 'earnings',
    'earnings_confirm': 'earnings',
    'dividend': 'earnings',              # 分红属基本面正向事件
    'report_date': 'earnings',
    'fraud_sign': 'fraud_sign',          # 对齐十类枚举
    'share_float': 'float',              # 对齐十类枚举
    'pledge_risk': 'pledge',
    'holder_reduce': 'reduce',           # 对齐十类枚举
    'underwater_ipo': 'pledge',          # 定增破发属资金面风险
    'buyback': 'buyback',
    'incentive': 'buyback',              # 股权激励类似回购，正向
    'regulatory': 'regulatory',
    'delist_risk': 'regulatory',         # 退市风险归监管类
    'st_warning': 'regulatory',
    'longhubang': 'lhb',
    'limit_move': 'breakout',            # 涨停属技术突破信号
    'holder_concentration': 'concept',   # 股东集中属资金面信号
    'margin_risk': 'pledge',             # 融资风险归质押类
    'breakout': 'breakout',
    'concept_heat': 'concept',           # 对齐十类枚举
}


def _direction_to_sign(direction: int) -> int:
    """direction → -1 / 0 / +1"""
    if direction > 0:
        return 1
    if direction < 0:
        return -1
    return 0


def _event_dim_prefix(event_name: str) -> str:
    """事件名 → 维度字母 (A/B/C/D/E)"""
    if event_name.startswith(('earnings', 'report', 'dividend', 'fraud')):
        return 'A'
    if event_name.startswith(('share', 'pledge', 'holder_r', 'underwater', 'buyback', 'incentive')):
        return 'B'
    if event_name.startswith(('regulatory', 'delist', 'st_w')):
        return 'C'
    if event_name.startswith(('lhb', 'limit', 'holder_c', 'margin')):
        return 'D'
    return 'E'


class EventMonitor(DataAwareMixin):
    """事件监控器"""

    def __init__(self, data_manager=None):
        self._dm = data_manager  # DataAwareMixin 统一注入点

    def _today_str(self) -> str:
        return datetime.now().strftime('%Y%m%d')

    def _date_from_str(self, s: str) -> date | None:
        try:
            s_clean = str(s).replace('-', '')[:8]
            if len(s_clean) == 8 and s_clean.isdigit():
                return datetime.strptime(s_clean, '%Y%m%d').date()
        except Exception:
            pass
        return None

    # ══════════════════════════════════════════════════════════
    # A 财务事件
    # ══════════════════════════════════════════════════════════

    def _detect_earnings_surprise(self, ts_code: str) -> dict:
        """A1 业绩预增: forecast_cache 净利润同比增长>50%"""
        result = {"detected": False, "direction": 0, "confidence": 0.0,
                   "source": "forecast_cache", "description": "", "event_date": ""}
        try:
            cache = self._get_cache()
            df = cache.get_cached_forecast(ts_code)
            if df is None or df.empty:
                return result

            # 取最新一条预告
            latest = df.sort_values('end_date', ascending=False).iloc[0]
            ftype = str(latest.get('forecast_type', ''))
            ftype_map = {
                '预增': ('正向', 1), '扭亏': ('正向', 1), '续盈': ('正向', 0),
                '略增': ('正向', 0), '减亏': ('正向', 0),
                '预减': ('负向', -1), '首亏': ('负向', -2), '续亏': ('负向', -2),
                '略减': ('负向', -1),
            }
            mapping = ftype_map.get(ftype)
            if mapping is None:
                return result

            label, base_dir = mapping
            # 检查净利同比增幅是否>50%
            n_min = latest.get('net_profit_min')
            n_max = latest.get('net_profit_max')
            direction = base_dir
            confidence = 0.5
            event_date = str(latest.get('ann_date', ''))

            if n_min is not None and n_max is not None and n_min != 0:
                avg_profit = (float(n_min) + float(n_max)) / 2
                # 如果有 end_date 可以算同比，但 forecast 表中只有绝对值
                # 简化为：预告类型正向且净利为正 → direction=+1, 大幅预增→+2
                if label == '正向' and avg_profit > 0:
                    direction = 2 if ftype == '预增' else 1
                    confidence = 0.7
                    result["detected"] = True
                elif label == '负向':
                    direction = base_dir
                    confidence = 0.6
                    result["detected"] = True

            result["direction"] = direction
            result["confidence"] = confidence
            result["description"] = f"业绩预告: {ftype}"
            result["event_date"] = event_date
        except Exception as e:
            logger.debug("A1 _detect_earnings_surprise(%s): %s", ts_code, e)
        return result

    def _detect_earnings_confirm(self, ts_code: str) -> dict:
        """A2 业绩确认: forecast_cache + fina_indicator — 偏差±10%"""
        result = {"detected": False, "direction": 0, "confidence": 0.0,
                   "source": "forecast_cache+fina_indicator", "description": "", "event_date": ""}
        try:
            cache = self._get_cache()
            df_fc = cache.get_cached_forecast(ts_code)
            df_fi = cache.get_cached_fina_indicator(ts_code)
            if df_fc is None or df_fc.empty or df_fi is None or df_fi.empty:
                return result

            latest_fc = df_fc.sort_values('end_date', ascending=False).iloc[0]
            # 匹配对应 end_date 的财报
            fc_end = str(latest_fc.get('end_date', ''))
            if not fc_end:
                return result
            match = df_fi[df_fi['end_date'] == fc_end]
            if match.empty:
                return result
            actual_eps = match.iloc[0].get('eps')
            if actual_eps is None:
                return result
            actual_eps = float(actual_eps)

            fc_eps_min = latest_fc.get('eps_min')
            fc_eps_max = latest_fc.get('eps_max')
            if fc_eps_min is None or fc_eps_max is None:
                return result
            fc_eps_min, fc_eps_max = float(fc_eps_min), float(fc_eps_max)

            if abs(fc_eps_min) < 1e-9:
                return result

            # 偏差: 实际值与预告中值比较
            fc_mid = (fc_eps_min + fc_eps_max) / 2
            if fc_mid == 0:
                return result
            deviation = (actual_eps - fc_mid) / abs(fc_mid)
            forecast_type = str(latest_fc.get('forecast_type', ''))

            # 正向偏差 = 业绩超预期
            direction = 0
            confidence = 0.0
            if abs(deviation) >= 0.1:
                result["detected"] = True
                direction = 1 if deviation > 0 else -1
                confidence = min(abs(deviation), 1.0)
                result["description"] = (
                    f"业绩确认偏差: {deviation:+.1%}, "
                    f"预告={forecast_type}, "
                    f"实际EPS={actual_eps:.4f}"
                )
                result["event_date"] = str(match.iloc[0].get('ann_date', ''))
            else:
                # 偏差<10%，确认符合预期
                pass

            result["direction"] = direction
            result["confidence"] = confidence
        except Exception as e:
            logger.debug("A2 _detect_earnings_confirm(%s): %s", ts_code, e)
        return result

    def _detect_report_date(self, ts_code: str) -> dict:
        """A3 财报预约披露日: 依赖 AKShare 巨潮公告，非采集层不可用
        第一阶段标记为未检测到。
        """
        return {"detected": False, "direction": 0, "confidence": 0.0,
                "source": "report_date", "description": "财报披露日检测待接入",
                "event_date": ""}

    def _detect_dividend(self, ts_code: str) -> dict:
        """A4 分红/送转: 依赖 AKShare 巨潮公告，非采集层不可用
        第一阶段标记为未检测到。
        """
        return {"detected": False, "direction": 0, "confidence": 0.0,
                "source": "dividend", "description": "分红送转检测待接入",
                "event_date": ""}

    def _detect_fraud_sign(self, ts_code: str) -> dict:
        """A5 财务异常: fina_indicator + income + cashflow 多项异常

        检测项（2026-08-05 收紧：原 ROE<3%/现金流<0.5 过宽，致 74.9% 股票误标 fraud_sign——
        财务质量差 ≠ 财务欺诈；收紧至真实异常阈值）:
        1) 营收连续2年下降
        2) 经营现金流为负（原 <0.5 过宽）
        3) ROE 为负（亏损，原 <3% 过宽；微利由 fina_health 覆盖）
        4) 资产负债率 > 90%
        """
        result = {"detected": False, "direction": 0, "confidence": 0.0,
                   "source": "fina_indicator+income+cashflow", "description": "", "event_date": ""}
        try:
            dm = self._get_dm()
            df_fi = dm.get_cached_fina_indicator(ts_code)
            df_inc = dm.get_cached_income(ts_code)
            df_cf = dm.cache.get_cached_cashflow(ts_code)
            df_bs = dm.get_cached_balancesheet(ts_code)

            anomalies = []

            # 1) 营收连续2年下降
            if df_inc is not None and len(df_inc) >= 2:
                inc_sorted = df_inc.sort_values('end_date', ascending=False)
                revenues = inc_sorted['revenue'].dropna()
                if len(revenues) >= 2:
                    if revenues.iloc[0] < revenues.iloc[1] * 0.9:
                        anomalies.append("营收连续下降")

            # 2) 经营现金流为负（原 <0.5 过宽，收紧为负）
            if df_cf is not None and df_inc is not None:
                cf_sorted = df_cf.sort_values('end_date', ascending=False)
                inc_sorted = df_inc.sort_values('end_date', ascending=False)
                if not cf_sorted.empty and not inc_sorted.empty:
                    ocf = cf_sorted.iloc[0].get('cashflow_oper') or 0
                    has_attr = 'n_income_attr_p' in inc_sorted.columns
                    n_col = 'n_income_attr_p' if has_attr else 'n_income'
                    ni = inc_sorted.iloc[0].get(n_col) or 0
                    if ocf < 0 and abs(ni) > 1e-6:
                        anomalies.append("经营现金流为负")

            # 3) ROE 为负（亏损；原 <3% 过宽，微利由 fina_health 覆盖）
            if df_fi is not None and 'roe' in df_fi.columns:
                roe = df_fi['roe'].dropna()
                if not roe.empty and roe.iloc[0] < 0:
                    anomalies.append(f"ROE={roe.iloc[0]:.1f}%<0")

            # 4) 资产负债率 > 90%
            if df_bs is not None:
                bs_sorted = df_bs.sort_values('end_date', ascending=False)
                ta = bs_sorted.iloc[0].get('total_assets') or 0
                tl = bs_sorted.iloc[0].get('total_liab') or 0
                if ta > 0 and tl / ta > 0.9:
                    anomalies.append(f"资产负债率>{tl/ta*100:.0f}%>90%")

            if len(anomalies) >= 2:
                result["detected"] = True
                result["direction"] = -2
                result["confidence"] = min(len(anomalies) / 4, 1.0)
                result["description"] = "多项财务异常: " + "; ".join(anomalies)
        except Exception as e:
            logger.debug("A5 _detect_fraud_sign(%s): %s", ts_code, e)
        return result

    # ══════════════════════════════════════════════════════════
    # B 资本运作
    # ══════════════════════════════════════════════════════════

    def _detect_share_float(self, ts_code: str) -> dict:
        """B1 限售股解禁>5%: share_float 表未入库，返回未检测到"""
        return {"detected": False, "direction": 0, "confidence": 0.0,
                "source": "share_float", "description": "限售股解禁数据未采集",
                "event_date": ""}

    def _detect_pledge_risk(self, ts_code: str) -> dict:
        """B2 质押>50%: pledge_stat 表未入库，返回未检测到"""
        return {"detected": False, "direction": 0, "confidence": 0.0,
                "source": "pledge_stat", "description": "质押数据未采集",
                "event_date": ""}

    def _detect_holder_reduce(self, ts_code: str) -> dict:
        """B3 减持预披露: stk_holdertrade 表未入库，返回未检测到"""
        return {"detected": False, "direction": 0, "confidence": 0.0,
                "source": "stk_holdertrade", "description": "股东减持数据未采集",
                "event_date": ""}

    def _detect_underwater_ipo(self, ts_code: str) -> dict:
        """B4 定增破发: share_float + adj_factor 表未入库，返回未检测到"""
        return {"detected": False, "direction": 0, "confidence": 0.0,
                "source": "share_float+adj_factor", "description": "定增破发检测待接入",
                "event_date": ""}

    def _detect_buyback(self, ts_code: str) -> dict:
        """B5 回购>5000万: repurchase 表未入库，返回未检测到"""
        return {"detected": False, "direction": 0, "confidence": 0.0,
                "source": "repurchase", "description": "回购数据未采集",
                "event_date": ""}

    def _detect_incentive(self, ts_code: str) -> dict:
        """B6 股权激励行权期: stk_rewards 表未入库，返回未检测到"""
        return {"detected": False, "direction": 0, "confidence": 0.0,
                "source": "stk_rewards", "description": "股权激励数据未采集",
                "event_date": ""}

    # ══════════════════════════════════════════════════════════
    # C 监管事件
    # ══════════════════════════════════════════════════════════

    def _detect_regulatory(self, ts_code: str) -> dict:
        """C1 立案调查: 检查 sentiment_pool_cache 异常波动标记"""
        result = {"detected": False, "direction": 0, "confidence": 0.0,
                   "source": "sentiment_pool_cache", "description": "", "event_date": ""}
        try:
            cache = self._get_cache()
            # 查 sentiment_pool 中是否有本股且 reason_category 含立案/调查
            df = cache.get_cached_sentiment_pool()
            if df is None or df.empty:
                return result
            df_stock = df[df['ts_code'] == ts_code]
            if df_stock.empty:
                return result
            # 检查 reason_category 是否含调查/监管关键词
            reason = str(df_stock.iloc[0].get('reason_category', ''))
            keywords = ['立案', '调查', '监管', '警示', '谴责', '处罚']
            if any(k in reason for k in keywords):
                result["detected"] = True
                result["direction"] = -2
                result["confidence"] = 0.8
                result["description"] = f"监管异常: {reason}"
                result["event_date"] = str(df_stock.iloc[0].get('trade_date', ''))
        except Exception as e:
            logger.debug("C1 _detect_regulatory(%s): %s", ts_code, e)
        return result

    def _detect_delist_risk(self, ts_code: str) -> dict:
        """C2 退市风险: 连续10日<1元 or 市值<3亿"""
        result = {"detected": False, "direction": 0, "confidence": 0.0,
                   "source": "daily_cache+daily_basic_cache", "description": "", "event_date": ""}
        try:
            dm = self._get_dm()
            df = dm.get_cached_daily_data(ts_code)
            if df is None or df.empty or len(df) < 10:
                return result

            df_sorted = df.sort_values('trade_date', ascending=False)
            recent = df_sorted.head(10)

            # 检查连续10日收盘<1元
            closes = recent['close'].dropna()
            if len(closes) >= 10 and (closes < 1.0).all():
                result["detected"] = True
                result["direction"] = -2
                result["confidence"] = 0.9
                result["description"] = f"连续10日收盘<1元 (最新{closes.iloc[0]:.2f})"
                result["event_date"] = str(recent.iloc[0]['trade_date'])
                return result

            # 检查市值<3亿
            df_basic = dm.get_cached_daily_basic(ts_code)
            if df_basic is not None and not df_basic.empty:
                mv = df_basic.sort_values('trade_date', ascending=False)
                if 'total_mv' in mv.columns:
                    latest_mv = mv['total_mv'].dropna()
                    if not latest_mv.empty and latest_mv.iloc[0] < 3e4:  # 万元
                        result["detected"] = True
                        result["direction"] = -2
                        result["confidence"] = 0.9
                        result["description"] = f"市值<3亿 (当前{latest_mv.iloc[0]:.0f}万)"
                        result["event_date"] = str(mv.iloc[0]['trade_date'])
        except Exception as e:
            logger.debug("C2 _detect_delist_risk(%s): %s", ts_code, e)
        return result

    def _detect_st_warning(self, ts_code: str) -> dict:
        """C3 ST/*ST 预警: 检查股票名称是否含 ST 标记"""
        result = {"detected": False, "direction": 0, "confidence": 0.0,
                   "source": "Stock ORM", "description": "", "event_date": self._today_str()}
        try:
            dm = self._get_dm()
            info = dm.get_stock_info(ts_code)
            if info is None:
                return result
            name = str(info.get('name', ''))
            if '*ST' in name:
                result["detected"] = True
                result["direction"] = -2
                result["confidence"] = 1.0
                result["description"] = f"*ST 预警: {name}"
            elif 'ST' in name:
                result["detected"] = True
                result["direction"] = -1
                result["confidence"] = 0.8
                result["description"] = f"ST 预警: {name}"
        except Exception as e:
            logger.debug("C3 _detect_st_warning(%s): %s", ts_code, e)
        return result

    # ══════════════════════════════════════════════════════════
    # D 市场情绪
    # ══════════════════════════════════════════════════════════

    def _detect_longhubang(self, ts_code: str) -> dict:
        """D1 龙虎榜: lhb_cache + lhb_detail — 机构净买>5000万"""
        result = {"detected": False, "direction": 0, "confidence": 0.0,
                   "source": "lhb_cache", "description": "", "event_date": ""}
        try:
            cache = self._get_cache()
            df_lhb = cache.get_cached_lhb(ts_code=ts_code)
            if df_lhb is None or df_lhb.empty:
                return result
            latest = df_lhb.sort_values('trade_date', ascending=False).iloc[0]
            net_amount = float(latest.get('net_amount', 0) or 0)
            event_date = str(latest.get('trade_date', ''))

            # 机构净买 > 5000万 → 正向
            if net_amount > 5e3:
                result["detected"] = True
                result["direction"] = 2
                result["confidence"] = min(net_amount / 2e4, 1.0)
                result["description"] = f"龙虎榜机构净买{net_amount/1e4:.0f}万"
                result["event_date"] = event_date

            # 机构净卖 > 5000万 → 负向
            elif net_amount < -5e3:
                result["detected"] = True
                result["direction"] = -2
                result["confidence"] = min(abs(net_amount) / 2e4, 1.0)
                result["description"] = f"龙虎榜机构净卖{abs(net_amount)/1e4:.0f}万"
                result["event_date"] = event_date

            # 也查 lhb_detail 中是否有机构席位
            if not result["detected"]:
                df_detail = cache.get_cached_lhb_detail(ts_code=ts_code)
                if df_detail is not None and not df_detail.empty:
                    detail = df_detail.sort_values('trade_date', ascending=False)
                    latest_detail = detail.iloc[0]
                    det_net = float(latest_detail.get('net_amount', 0) or 0)
                    if abs(det_net) > 5e3:
                        result["detected"] = True
                        result["direction"] = 2 if det_net > 0 else -2
                        result["confidence"] = min(abs(det_net) / 2e4, 1.0)
                        seat = latest_detail.get('seat_name', '')
                        result["description"] = f"龙虎榜席位净{abs(det_net)/1e4:.0f}万 ({seat})"
                        result["event_date"] = str(latest_detail.get('trade_date', ''))
        except Exception as e:
            logger.debug("D1 _detect_longhubang(%s): %s", ts_code, e)
        return result

    def _detect_limit_move(self, ts_code: str) -> dict:
        """D2 涨停/跌停/炸板: daily_cache pct_chg"""
        result = {"detected": False, "direction": 0, "confidence": 0.0,
                   "source": "daily_cache", "description": "", "event_date": ""}
        try:
            dm = self._get_dm()
            df = dm.get_cached_daily_data(ts_code)
            if df is None or df.empty or len(df) < 3:
                return result
            df_sorted = df.sort_values('trade_date', ascending=False)
            latest = df_sorted.iloc[0]
            prev = df_sorted.iloc[1] if len(df_sorted) > 1 else None
            pct_chg = float(latest.get('pct_chg', 0) or 0)
            event_date = str(latest.get('trade_date', ''))

            # 涨停
            if pct_chg >= 9.5:
                # 检查前一日是否涨停（连板）
                prev_limit = False
                if prev is not None:
                    prev_pct = float(prev.get('pct_chg', 0) or 0)
                    prev_limit = prev_pct >= 9.5

                direction = 2
                confidence = 0.8
                desc = "涨停"
                if prev_limit:
                    desc = "连板涨停"
                    direction = 2
                    confidence = 0.9
                result["detected"] = True
                result["direction"] = direction
                result["confidence"] = confidence
                result["description"] = desc
                result["event_date"] = event_date

            # 跌停
            elif pct_chg <= -9.5:
                result["detected"] = True
                result["direction"] = -2
                result["confidence"] = 0.8
                result["description"] = "跌停"
                result["event_date"] = event_date

            # 炸板（盘中涨停后回落）
            elif prev is not None:
                prev_pct = float(prev.get('pct_chg', 0) or 0)
                high = float(latest.get('high', 0) or 0)
                close = float(latest.get('close', 0) or 0)
                prev_close = float(prev.get('close', 0) or 0)
                if prev_close > 0 and (high / prev_close - 1) >= 0.095:
                    # 盘中触涨停但收盘回落
                    if (close / prev_close - 1) < 0.09:
                        result["detected"] = True
                        result["direction"] = -1
                        result["confidence"] = 0.6
                        result["description"] = "炸板（盘中涨停后回落）"
                        result["event_date"] = event_date
        except Exception as e:
            logger.debug("D2 _detect_limit_move(%s): %s", ts_code, e)
        return result

    def _detect_holder_concentration(self, ts_code: str) -> dict:
        """D3 股东户数减少>10%: stk_holder_cache"""
        result = {"detected": False, "direction": 0, "confidence": 0.0,
                   "source": "stk_holder_cache", "description": "", "event_date": ""}
        try:
            cache = self._get_cache()
            df = cache.get_cached_stk_holder(ts_code)
            if df is None or df.empty or len(df) < 2:
                return result
            df_sorted = df.sort_values('end_date', ascending=False)
            latest = df_sorted.iloc[0]
            prev = df_sorted.iloc[1]
            ln = float(latest.get('holder_number', 0) or 0)
            pn = float(prev.get('holder_number', 0) or 0)
            if pn <= 0:
                return result
            change = (ln - pn) / pn
            event_date = str(latest.get('end_date', ''))

            if change <= -0.10:
                result["detected"] = True
                result["direction"] = 1
                result["confidence"] = min(abs(change) * 3, 1.0)
                result["description"] = f"股东户数减少{abs(change)*100:.0f}% (集中)"
                result["event_date"] = event_date
            elif change >= 0.20:
                result["detected"] = True
                result["direction"] = -1
                result["confidence"] = min(change * 2, 1.0)
                result["description"] = f"股东户数增加{change*100:.0f}% (分散)"
                result["event_date"] = event_date
        except Exception as e:
            logger.debug("D3 _detect_holder_concentration(%s): %s", ts_code, e)
        return result

    def _detect_margin_risk(self, ts_code: str) -> dict:
        """D4 融资余额增加>20%: margin_cache"""
        result = {"detected": False, "direction": 0, "confidence": 0.0,
                   "source": "margin_cache", "description": "", "event_date": ""}
        try:
            cache = self._get_cache()
            df = cache.get_cached_margin(ts_code)
            if df is None or df.empty or len(df) < 5:
                return result
            df_sorted = df.sort_values('trade_date', ascending=False)
            # 最近5日平均 vs 之前5日平均
            recent = df_sorted.head(5)
            older = df_sorted.iloc[5:10]
            if len(older) < 3:
                return result

            recent_avg = recent['rzye'].dropna().mean()
            older_avg = older['rzye'].dropna().mean()
            if pd.isna(recent_avg) or pd.isna(older_avg) or older_avg <= 0:
                return result

            change = (recent_avg - older_avg) / older_avg
            event_date = str(df_sorted.iloc[0].get('trade_date', ''))

            if change >= 0.20:
                result["detected"] = True
                result["direction"] = 1
                result["confidence"] = min(change, 1.0)
                result["description"] = f"融资余额增加{change*100:.0f}% (>20%)"
                result["event_date"] = event_date
            elif change <= -0.15:
                result["detected"] = True
                result["direction"] = -1
                result["confidence"] = min(abs(change), 1.0)
                result["description"] = f"融资余额减少{abs(change)*100:.0f}% (>15%)"
                result["event_date"] = event_date
        except Exception as e:
            logger.debug("D4 _detect_margin_risk(%s): %s", ts_code, e)
        return result

    # ══════════════════════════════════════════════════════════
    # E 特殊事件
    # ══════════════════════════════════════════════════════════

    def _detect_breakout(self, ts_code: str) -> dict:
        """E1 突破形态: 量价突破（站上60日线+放量+创20日新高）"""
        result = {"detected": False, "direction": 0, "confidence": 0.0,
                   "source": "daily_cache", "description": "", "event_date": ""}
        try:
            dm = self._get_dm()
            df = dm.get_cached_daily_data(ts_code)
            if df is None or df.empty or len(df) < 60:
                return result
            df_sorted = df.sort_values('trade_date').reset_index(drop=True)
            closes = df_sorted['close'].values
            volumes = df_sorted['vol'].values

            if len(closes) < 60:
                return result

            cur_close = closes[-1]

            # MA60
            ma60 = np.mean(closes[-60:])

            # 站上 MA60
            above_ma60 = cur_close > ma60 * 1.02

            # 量比 >1.5（近5日均量 vs 近20日均量）
            vol_ma5 = np.mean(volumes[-5:])
            vol_ma20 = np.mean(volumes[-20:])
            vol_ratio = vol_ma5 / max(vol_ma20, 1)
            volume_surge = vol_ratio > 1.5

            # 创20日新高
            new_high = cur_close >= np.max(closes[-20:-1]) * 0.99

            factors = sum([above_ma60, volume_surge, new_high])
            if factors >= 2:
                result["detected"] = True
                result["direction"] = 1 if cur_close > ma60 else -1
                result["confidence"] = factors / 3.0
                parts = []
                if above_ma60:
                    parts.append("站上60日线")
                if volume_surge:
                    parts.append(f"放量{vol_ratio:.1f}倍")
                if new_high:
                    parts.append("20日新高")
                result["description"] = "突破: " + "+".join(parts)
                result["event_date"] = str(df_sorted.iloc[-1]['trade_date'])
        except Exception as e:
            logger.debug("E1 _detect_breakout(%s): %s", ts_code, e)
        return result

    def _detect_concept_heat(self, ts_code: str) -> dict:
        """E2 概念热度: 概念板块热度排名升20位
        第一阶段简化：检查概念所属板块数 > 3 标记为活跃概念股。
        """
        result = {"detected": False, "direction": 0, "confidence": 0.0,
                   "source": "concept_cache", "description": "", "event_date": ""}
        try:
            cache = self._get_cache()
            df = cache.get_cached_concept(ts_code)
            if df is None or df.empty:
                return result
            # 股票拥有的概念数
            n_concepts = len(df)
            # 全市场概念分布 → 找出该股票所属概念中成员最多的
            all_concepts = cache.get_cached_concept()
            if all_concepts is None or all_concepts.empty:
                return result
            concept_counts = all_concepts['concept_name'].value_counts()
            # 计算该股票所属概念的平均热度排名
            stock_concepts = df['concept_name'].unique()
            ranks = []
            for i, (cname, cnt) in enumerate(concept_counts.items()):
                if cname in stock_concepts:
                    ranks.append(i + 1)
            if not ranks:
                return result
            avg_rank = sum(ranks) / len(ranks)
            # 概念数量 > 3 且平均排名在前50% → 概念活跃
            if n_concepts > 3 and avg_rank <= len(concept_counts) / 2:
                result["detected"] = True
                result["direction"] = 1
                result["confidence"] = 0.5
                result["description"] = f"概念活跃({n_concepts}个概念, 平均排名第{avg_rank:.0f})"
        except Exception as e:
            logger.debug("E2 _detect_concept_heat(%s): %s", ts_code, e)
        return result

    # ══════════════════════════════════════════════════════════
    # 新闻质量过滤（P2.1 第一阶段简化版）
    # ══════════════════════════════════════════════════════════

    def _news_quality_filter(self, event_type: str, event: dict) -> float:
        """新闻质量过滤，返回 0~1 质量分
        仅 D 类事件（D1/D2）需要过滤：

        Phase 1 简化三因子:
        1) 来源分级（默认0.7~1.0，当前统一给 0.9）
        2) 蹭热点检测: 描述含敏感词→折扣
        3) 旧闻检测: event_date 早于3日→折扣
        """
        if event_type not in ('longhubang', 'limit_move'):
            return 1.0

        score = 0.9  # 基础分

        # 蹭热点检测
        desc = event.get('description', '')
        clickbait_keywords = ['突发', '重磅', '紧急', '震惊', '大利好', '大利空',
                              '抄底', '逃顶', '速看', '涨停板敢死队']
        for kw in clickbait_keywords:
            if kw in desc:
                score *= 0.8
                break

        # 旧闻检测（event_date 早于3天前）
        event_date_str = event.get('event_date', '')
        if event_date_str:
            try:
                ed = self._date_from_str(event_date_str)
                if ed is not None:
                    delta = (datetime.now().date() - ed).days
                    if delta > 3:
                        score *= 0.5
                    elif delta > 1:
                        score *= 0.8
            except Exception:
                pass

        return max(0.0, min(1.0, score))

    # ══════════════════════════════════════════════════════════
    # 主入口
    # ══════════════════════════════════════════════════════════

    def detect_all(self, ts_code: str) -> dict:
        """全量检测 20 类事件

        Returns:
            events: 所有检测到的事件列表
            event_composite_score: -5 ~ +5
            event_calendar_upcoming: 日历事件（待定）
            news_quality_score: 0-1
            catalyst_event: 催化剂事件类型
            catalyst_impact: 'high'|'medium'|'low'
            upward_driver: 上涨驱动力类型
        """
        # ── 各维度事件检测 ──
        detectors = [
            # A 财务
            ('earnings_surprise', self._detect_earnings_surprise),
            ('earnings_confirm', self._detect_earnings_confirm),
            ('report_date', self._detect_report_date),
            ('dividend', self._detect_dividend),
            ('fraud_sign', self._detect_fraud_sign),
            # B 资本运作
            ('share_float', self._detect_share_float),
            ('pledge_risk', self._detect_pledge_risk),
            ('holder_reduce', self._detect_holder_reduce),
            ('underwater_ipo', self._detect_underwater_ipo),
            ('buyback', self._detect_buyback),
            ('incentive', self._detect_incentive),
            # C 监管
            ('regulatory', self._detect_regulatory),
            ('delist_risk', self._detect_delist_risk),
            ('st_warning', self._detect_st_warning),
            # D 市场情绪
            ('longhubang', self._detect_longhubang),
            ('limit_move', self._detect_limit_move),
            ('holder_concentration', self._detect_holder_concentration),
            ('margin_risk', self._detect_margin_risk),
            # E 特殊
            ('breakout', self._detect_breakout),
            ('concept_heat', self._detect_concept_heat),
        ]

        events: list[dict] = []
        dim_max: dict[str, int] = {'A': 0, 'B': 0, 'C': 0, 'D': 0, 'E': 0}
        dim_direction: dict[str, int] = {'A': 0, 'B': 0, 'C': 0, 'D': 0, 'E': 0}
        quality_scores: list[float] = []

        for event_name, detect_fn in detectors:
            try:
                event = detect_fn(ts_code)
            except Exception as e:
                logger.warning("事件检测 %s(%s) 异常: %s", event_name, ts_code, e)
                event = {"detected": False, "direction": 0, "confidence": 0.0,
                          "source": event_name, "description": "", "event_date": ""}

            if event.get('detected'):
                # 新闻质量过滤（仅 D1/D2）
                event_type_key = event_name
                q = self._news_quality_filter(event_type_key, event)
                quality_scores.append(q)

                if event_type_key in ('longhubang', 'limit_move'):
                    if q < 0.3:
                        # 不进入评分，仅保留展示
                        event['confidence'] = 0.0
                    elif q < 0.7:
                        # 折扣
                        event['confidence'] *= q
                        event['description'] += " [质量折扣]"

                events.append({
                    'event_type': event_name,
                    **event,
                })

                # 更新维度极值
                prefix = _event_dim_prefix(event_name)
                abs_dir = abs(event['direction'])
                if abs_dir > abs(dim_max[prefix]):
                    dim_max[prefix] = abs_dir
                    dim_direction[prefix] = _direction_to_sign(event['direction'])

        # ── 评分合并 ──
        max_abs = 0
        composite_direction = 0
        for prefix in ['A', 'B', 'C', 'D', 'E']:
            if dim_max[prefix] > max_abs:
                max_abs = dim_max[prefix]
                composite_direction = dim_direction[prefix] if dim_direction[prefix] != 0 else 1

        event_composite_score = composite_direction * max_abs if max_abs > 0 else 0

        # ── 新闻综合质量分 ──
        news_quality_score = float(np.mean(quality_scores)) if quality_scores else 1.0

        # ── catalyst 判定（取 abs 最大的事件的类型） ──
        catalyst_event = 'none'
        catalyst_impact: str = 'low'
        best_abs = 0
        for ev in events:
            if abs(ev.get('direction', 0)) > best_abs:
                best_abs = abs(ev['direction'])
                catalyst_event = CATALYST_EVENT_MAP.get(ev.get('event_type', ''), 'none')
        if best_abs >= 2:
            catalyst_impact = 'high'
        elif best_abs >= 1:
            catalyst_impact = 'medium'

        # ── 上涨驱动力判定（upward_driver, 295号§3.4 标签25） ──
        if catalyst_event in ('earnings', 'lhb', 'buyback'):
            upward_driver = 'info_driven'
        elif catalyst_event in ('breakout',):
            upward_driver = 'emotion_driven'
        elif catalyst_event in ('concept',):
            upward_driver = 'emotion_driven'
        elif catalyst_event == 'none':
            upward_driver = 'no_upward'
        else:
            upward_driver = 'mixed'

        return {
            'events': events,
            'event_composite_score': event_composite_score,
            'event_calendar_upcoming': [],
            'news_quality_score': round(news_quality_score, 2),
            'catalyst_event': catalyst_event,
            'catalyst_impact': catalyst_impact,
            'upward_driver': upward_driver,
        }

    def compute_tags(self, ts_code: str) -> dict:
        """事件监控标签（供 ECM write_tags 使用）"""
        try:
            result = self.detect_all(ts_code)
        except Exception as e:
            logger.error("EventMonitor.compute_tags(%s) 失败: %s", ts_code, e)
            return {
                'catalyst_event': 'none',
                'catalyst_impact': 'low',
                'event_composite_score': 0,
            }

        tags: dict[str, Any] = {
            'catalyst_event': result['catalyst_event'],
            'catalyst_impact': result['catalyst_impact'],
            'event_composite_score': result['event_composite_score'],
            'upward_driver': result.get('upward_driver', 'no_upward'),
        }

        # 写事件摘要（最多3条）
        events = result.get('events', [])
        if events:
            event_summaries = []
            for ev in events[:3]:
                desc = ev.get('description', '')
                if desc:
                    event_summaries.append(desc)
            if event_summaries:
                tags['event_summary'] = '; '.join(event_summaries)

        return tags
