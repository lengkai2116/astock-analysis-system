"""
回测赢率证据服务

封装 SignalWinRateEvaluator，提供：
  1. 逐信号生命周期管理（pending → t5_checked → ... → completed）
  2. 批量回调检查（定时任务入口）
  3. 条件概率评估
"""
import logging
from typing import Dict, List, Optional
from datetime import datetime, date, timedelta
import pandas as pd
import numpy as np

from app import db
from app.data import DataManager
from app.models.verification import SignalRecord, VirtualPosition
from app.engine.framework.backtest_evidence import (
    SignalWinRateEvaluator, SignalClassifier,
)

logger = logging.getLogger(__name__)


class BacktestEvidenceService:
    """回测赢率证据服务"""

    def __init__(self):
        self.evaluator = SignalWinRateEvaluator()
        self._data_manager = None

    @property
    def data_manager(self):
        if self._data_manager is None:
            self._data_manager = DataManager()
        return self._data_manager

    # ── 轨A: SignalRecord 管理 ──

    def record_signal(self, ts_code: str, strategy_name: str, signal_type: str,
                      confidence: float = 0.0, entry_price: float = None,
                      risk_line: float = None, target_price: float = None,
                      entry_zone_low: float = None, entry_zone_high: float = None,
                      signal_snapshot: dict = None) -> Optional[SignalRecord]:
        """记录一条策略信号（轨A·后台自动）"""
        try:
            record = SignalRecord(
                ts_code=ts_code,
                signal_date=date.today(),
                strategy_name=strategy_name,
                signal_type=signal_type,
                confidence=confidence,
                entry_price=entry_price,
                risk_line=risk_line,
                target_price=target_price,
                entry_zone_low=entry_zone_low,
                entry_zone_high=entry_zone_high,
                verification_status='pending',
                signal_snapshot=signal_snapshot,
            )
            db.session.add(record)
            db.session.commit()
            return record
        except Exception as e:
            db.session.rollback()
            logger.warning(f"记录信号失败 {ts_code}/{signal_type}: {e}")
            return None

    # ── 轨B: VirtualPosition 管理 ──

    def create_virtual_position(self, ts_code: str, stock_name: str,
                                 suggestion: str, entry_price: float,
                                 entry_zone_low: float, entry_zone_high: float,
                                 risk_line: float, target_price: float,
                                 position_suggestion: str, confidence: float,
                                 virtual_capital: float = 100000.0) -> Optional[VirtualPosition]:
        """创建虚拟实盘持仓（轨B·用户可选）"""
        try:
            vp = VirtualPosition(
                ts_code=ts_code,
                stock_name=stock_name,
                suggestion=suggestion,
                entry_price=entry_price,
                entry_zone_low=entry_zone_low,
                entry_zone_high=entry_zone_high,
                risk_line=risk_line,
                target_price=target_price,
                position_suggestion=position_suggestion,
                confidence=confidence,
                virtual_capital=virtual_capital,
                start_date=date.today(),
                status='tracking',
            )
            db.session.add(vp)
            db.session.commit()
            return vp
        except Exception as e:
            db.session.rollback()
            logger.warning(f"创建虚拟持仓失败 {ts_code}: {e}")
            return None

    def get_virtual_positions(self, status: Optional[str] = None) -> List[VirtualPosition]:
        """获取虚拟持仓列表"""
        query = VirtualPosition.query.order_by(VirtualPosition.start_date.desc())
        if status:
            query = query.filter_by(status=status)
        return query.all()

    # ── 回调检查（定时任务入口） ──

    def run_checkpoint_update(self, days_offset: int = 5):
        """
        执行指定偏移量的回调检查

        2026-08-16 修复（345号第③层核查激活）：原实现按
        `signal_date == target_date`（精确日期匹配）查信号——历史积压
        （1083 条 pending，07-09~08-15 各日期）永不命中，导致从未回算。
        改为"已达 T+N 且未完成对应检查点"的信号（signal_date <= 今天-N），
        覆盖历史积压与当日新信号。

        Args:
            days_offset: 5 / 10 / 20 — 检查哪个时间窗口
        """
        cutoff = date.today() - timedelta(days=days_offset)
        label = f't{days_offset}'

        # 轨A: SignalRecord（已达 T+N 且未回算该检查点）
        if days_offset == 5:
            status_filter = SignalRecord.verification_status.in_(['pending'])
        elif days_offset == 10:
            status_filter = SignalRecord.verification_status.in_(['pending', 't5_checked'])
        else:  # 20
            status_filter = SignalRecord.verification_status.in_(['pending', 't5_checked', 't10_checked'])
        pending = SignalRecord.query.filter(
            SignalRecord.signal_date <= cutoff,
            status_filter
        ).all()

        for rec in pending:
            self._check_single_record(rec, days_offset, label)

        # 轨B: VirtualPosition（同轨A：覆盖历史积压）
        vp_pending = VirtualPosition.query.filter(
            VirtualPosition.start_date <= cutoff,
            VirtualPosition.status == 'tracking'
        ).all()
        for vp in vp_pending:
            self._check_single_vp(vp, days_offset, label)

        logger.info(f"回调检查 T+{days_offset}: SignalRecord={len(pending)}, VP={len(vp_pending)}")

    @staticmethod
    def _record_is_bullish(rec: SignalRecord) -> bool:
        """方向语义判断：新记录 signal_type=右侧信号类型（334号 S2.8，signal_registry.yaml 5 类），
        方向从 signal_snapshot.direction 读取（enter/light=看多）；旧记录 signal_type
        仍为方向枚举（BULLISH/WATCH=看多）时兼容回退。"""
        if rec.signal_type in ('BULLISH', 'WATCH'):
            return True
        try:
            snap = rec.signal_snapshot or {}
            if isinstance(snap, str):
                import json as _json
                snap = _json.loads(snap)
            return snap.get('direction') in ('enter', 'light')
        except Exception:
            return False

    def _check_single_record(self, rec: SignalRecord, days_offset: int, label: str):
        """更新单条 SignalRecord 的回调检查点

        2026-08-16 修复（345号第③层核查激活）：原实现把窗口末尾当信号价、
        往前数 offset 天当检查价——收益方向错乱。改为按 signal_date 精确定位，
        signal_price=信号日收盘，check_price=信号日后第 N 个交易日收盘。
        """
        try:
            df = self.data_manager.get_cached_daily_data(
                rec.ts_code,
                start_date=(rec.signal_date - timedelta(days=5)).strftime('%Y-%m-%d'),
                end_date=(rec.signal_date + timedelta(days=days_offset * 2 + 10)).strftime('%Y-%m-%d'),
            )
            if df.empty:
                return

            closes = df['close'].values
            dates = df['trade_date'].astype(str).values if 'trade_date' in df.columns else None
            # 定位 signal_date 在窗口中的索引
            sig_str = rec.signal_date.strftime('%Y-%m-%d')
            if dates is not None:
                try:
                    sig_idx = list(dates).index(sig_str)
                except ValueError:
                    # 信号日可能非交易日，找该日之后最近交易日
                    sig_idx = next((i for i, d in enumerate(dates) if d >= sig_str), None)
                    if sig_idx is None:
                        return
            else:
                sig_idx = len(closes) - 1  # 兜底：信号日=窗口末（无日期列时近似）

            signal_price = float(closes[sig_idx])
            target_idx = sig_idx + days_offset
            if target_idx >= len(closes):
                return  # T+N 尚未到达（未来数据不足）
            check_price = float(closes[target_idx])

            if signal_price == 0:
                return

            ret = (check_price - signal_price) / signal_price

            # 填充
            if days_offset == 5:
                rec.price_t5 = check_price
                rec.return_t5 = round(ret, 4)
                rec.hit_target_t5 = rec.target_price and check_price >= rec.target_price if self._record_is_bullish(rec) else False
                rec.hit_stop_t5 = rec.risk_line and check_price <= rec.risk_line
                rec.is_win_5d = ret > 0 if self._record_is_bullish(rec) else ret < 0
                rec.verification_status = 't5_checked'
            elif days_offset == 10:
                rec.price_t10 = check_price
                rec.return_t10 = round(ret, 4)
                rec.hit_target_t10 = rec.target_price and check_price >= rec.target_price if self._record_is_bullish(rec) else False
                rec.hit_stop_t10 = rec.risk_line and check_price <= rec.risk_line
                rec.is_win_10d = ret > 0 if self._record_is_bullish(rec) else ret < 0
                rec.verification_status = 't10_checked'
            elif days_offset == 20:
                rec.price_t20 = check_price
                rec.return_t20 = round(ret, 4)
                rec.hit_target_t20 = rec.target_price and check_price >= rec.target_price if self._record_is_bullish(rec) else False
                rec.hit_stop_t20 = rec.risk_line and check_price <= rec.risk_line
                # max drawdown：信号日后 T+1..T+20 区间内最大回撤
                seg = closes[sig_idx + 1:target_idx + 1]
                if len(seg) > 1:
                    peak = np.maximum.accumulate(seg[::-1])[::-1]
                    dd = (peak - seg) / peak
                    rec.max_drawdown_t20 = round(float(np.max(dd)), 4)
                rec.is_win_20d = ret > 0 if self._record_is_bullish(rec) else ret < 0
                rec.verification_status = 'completed'

            db.session.commit()

        except Exception as e:
            logger.debug(f"SignalRecord {rec.id} T+{days_offset} 检查失败: {e}")

    def _check_single_vp(self, vp: VirtualPosition, days_offset: int, label: str):
        """更新单条 VirtualPosition 的回调检查点"""
        try:
            df = self.data_manager.get_cached_daily_data(
                vp.ts_code,
                start_date=(vp.start_date - timedelta(days=5)).strftime('%Y-%m-%d'),
                end_date=(vp.start_date + timedelta(days=days_offset + 5)).strftime('%Y-%m-%d'),
            )
            if df.empty:
                return

            closes = df['close'].values
            entry = vp.entry_price or float(closes[-1])
            target_idx = min(days_offset, len(closes) - 1)
            check_price = float(closes[-1 - target_idx]) if len(closes) > target_idx else None
            if check_price is None or entry == 0:
                return

            ret = (check_price - entry) / entry

            if days_offset == 5:
                vp.price_t5 = check_price
                vp.return_t5 = round(ret, 4)
            elif days_offset == 10:
                vp.price_t10 = check_price
                vp.return_t10 = round(ret, 4)
            elif days_offset == 20:
                vp.price_t20 = check_price
                vp.return_t20 = round(ret, 4)
                vp.status = 'completed'
                # 判定
                if vp.suggestion in ('BUY', 'WATCH'):
                    vp.hit_target = vp.target_price and check_price >= vp.target_price
                    vp.hit_stop = vp.risk_line and check_price <= vp.risk_line
                else:
                    vp.hit_target = vp.target_price and check_price <= vp.target_price
                    vp.hit_stop = vp.risk_line and check_price >= vp.risk_line

                # 最终判定
                if vp.suggestion in ('BUY', 'WATCH'):
                    if ret > 0.05:
                        vp.final_judgement = 'CORRECT'
                    elif ret < -0.05:
                        vp.final_judgement = 'WRONG'
                    else:
                        vp.final_judgement = 'PARTIAL'
                elif vp.suggestion == 'SELL':
                    if ret < -0.03:
                        vp.final_judgement = 'CORRECT'
                    elif ret > 0.03:
                        vp.final_judgement = 'WRONG'
                    else:
                        vp.final_judgement = 'PARTIAL'
                else:
                    vp.final_judgement = 'PARTIAL'

                if vp.hit_stop:
                    vp.deviation_analysis = f"触发止损: 入场{entry:.2f}, 止损{vp.risk_line:.2f}, T+20价{check_price:.2f}"
                elif vp.hit_target:
                    vp.deviation_analysis = f"目标达成: 入场{entry:.2f}, 目标{vp.target_price:.2f}, T+20价{check_price:.2f}"
                else:
                    vp.deviation_analysis = f"未触目标也未触止损: T+20收益{ret*100:.1f}%"

            db.session.commit()

        except Exception as e:
            logger.debug(f"VirtualPosition {vp.id} T+{days_offset} 检查失败: {e}")

    # ── 批量赢率评估（月度/按需） ──

    def run_batch_evaluation(self, months_back: int = 6) -> Dict[str, Dict]:
        """
        批量评估历史信号的赢率

        从 SignalRecord 表中读取最近 N 个月已完成验证的信号，
        使用 SignalWinRateEvaluator 评估，并缓存结果。
        """
        cutoff = date.today() - timedelta(days=months_back * 30)
        records = SignalRecord.query.filter(
            SignalRecord.signal_date >= cutoff,
            SignalRecord.verification_status == 'completed'
        ).all()

        if not records:
            logger.info(f"最近{months_back}个月无已完成验证的信号")
            return {}

        signals = []
        price_data = {}
        for rec in records:
            sig = {
                'ts_code': rec.ts_code,
                'signal_type': rec.signal_type,
                'signal_date': rec.signal_date.strftime('%Y-%m-%d'),
                'strategy_name': rec.strategy_name,
            }
            signals.append(sig)
            if rec.ts_code not in price_data:
                df = self.data_manager.get_cached_daily_data(rec.ts_code)
                if not df.empty:
                    price_data[rec.ts_code] = df

        win_rates = self.evaluator.evaluate(signals, price_data)
        self._cache_win_rates(win_rates)
        logger.info(f"批量评估完成: {len(win_rates)} 类信号")
        return win_rates

    def _cache_win_rates(self, win_rates: Dict[str, Dict]):
        """缓存赢率数据"""
        try:
            import pandas as pd
            records = []
            for sig_type, wr in win_rates.items():
                records.append({
                    'signal_type': sig_type,
                    'samples': wr.get('samples', 0),
                    'win_rate_5d': wr.get('win_rate_5d', 0),
                    'win_rate_10d': wr.get('win_rate_10d', 0),
                    'win_rate_20d': wr.get('win_rate_20d', 0),
                    'avg_return_5d': wr.get('avg_return_5d', 0),
                    'avg_return_20d': wr.get('avg_return_20d', 0),
                    'sharpe_5d': wr.get('sharpe_5d', 0),
                    'sharpe_20d': wr.get('sharpe_20d', 0),
                    'evaluated_at': datetime.now().isoformat(),
                })
            if records:
                df = pd.DataFrame(records)
                self.data_manager.cache.cache_win_rates(df)
        except Exception as e:
            logger.warning(f"缓存赢率数据失败: {e}")

    def get_win_rates(self, signal_type: Optional[str] = None) -> Dict:
        """获取缓存的赢率数据"""
        try:
            wr = self.data_manager.cache.get_cached_win_rate(signal_type)
            if wr:
                return wr
        except Exception:
            pass
        return {}
