"""
复盘中心 V3 服务层

Phase 0: 数据库 CRUD + 基础统计
Phase 1: 模拟执行引擎 + 九维诊断
Phase 2: 报告系统 + 跨页通信
"""
import json
import logging
import math
import random
import threading
from datetime import datetime, date, timedelta
from typing import Dict, List, Optional, Tuple

from app import db
from app.models.playback import ReviewUnit, PlaybackAccount, PlaybackReport, ReviewConfig

logger = logging.getLogger(__name__)


class PlaybackV3Service:
    """复盘中心 V3 服务（池管理 + 模拟引擎 + 诊断）"""

    # 退出原因枚举
    EXIT_REASONS = {
        'stop_loss_hit': '止损',
        'take_profit_tier1': '止盈Tier1(半仓)',
        'take_profit_tier2': '止盈Tier2(全仓)',
        'circuit_breaker': '熔断',
        'signal_reversal': '信号反转',
        'time_stop': '超时平仓',
        'manual_close': '手动平仓',
    }

    # 根因层定义
    LAYERS = {
        'Layer1': ['direction', 'conflict'],
        'Layer2': ['verify'],
        'Layer3': ['arbitration', 'scenario'],
        'Layer4': ['entry', 'exit'],
        'Layer5': ['stop_tp', 'capital'],
    }

    def __init__(self):
        self._lock = threading.Lock()

    # ────────────────────────────────────────────────
    # Phase 0: 基础 CRUD
    # ────────────────────────────────────────────────

    def get_pool(self, stage: str = 'all', page: int = 1, size: int = 50,
                 strategy: str = '', search: str = '') -> Tuple[List, int, Dict]:
        """获取复盘池列表（含阶段筛选+分页+搜索）"""
        query = ReviewUnit.query.filter(ReviewUnit.deleted_at.is_(None))

        if stage and stage != 'all':
            query = query.filter(ReviewUnit.stage == stage)
        if strategy:
            query = query.filter(ReviewUnit.strategy_config['dimensions'].astext.contains(strategy))
        if search:
            pattern = f'%{search}%'
            query = query.filter(
                db.or_(ReviewUnit.ts_code.like(pattern), ReviewUnit.name.like(pattern))
            )

        # 统计各阶段数量
        total = query.count()
        stages = {
            'pending': ReviewUnit.query.filter_by(stage='pending', deleted_at=None).count(),
            'holding': ReviewUnit.query.filter_by(stage='holding', deleted_at=None).count(),
            'completed': ReviewUnit.query.filter_by(stage='completed', deleted_at=None).count(),
        }

        # 分页
        items = query.order_by(ReviewUnit.added_at.desc()).offset((page - 1) * size).limit(size).all()
        result = [u.to_list_item() for u in items]
        return result, total, stages

    def add_entry(self, data: Dict) -> ReviewUnit:
        """新增复盘条目（从indicator-ide接收）"""
        meta = data.get('meta', {})

        # 生成 RV-ID
        max_id = db.session.query(db.func.max(ReviewUnit.id)).scalar() or 0
        unit_id = f'RV-{max_id + 1:03d}'

        unit = ReviewUnit(
            unit_id=unit_id,
            ts_code=meta.get('ts_code', ''),
            name=meta.get('name', ''),
            sector=meta.get('sector', ''),
            snapshot_date=self._parse_date(meta.get('snapshot_date')),
            base_price=meta.get('base_price'),
            added_at=datetime.now(),
            strategy_config=data.get('strategy_config'),
            dimension_outputs=data.get('dimension_outputs'),
            direction=data.get('direction', 'bullish'),
            timestamp=data.get('timestamp'),
            stage='pending',
            stage_progress_pct=0,
            events=[],
            capital_allocation={},
        )
        db.session.add(unit)
        db.session.commit()
        logger.info(f"复盘条目已创建: {unit_id} / {meta.get('ts_code')}")
        return unit

    def get_entry(self, unit_id: str) -> Optional[ReviewUnit]:
        """获取单个复盘条目详情"""
        unit = ReviewUnit.query.filter_by(unit_id=unit_id, deleted_at=None).first()
        return unit

    def update_entry(self, unit_id: str, data: Dict) -> Optional[ReviewUnit]:
        """更新复盘条目（手动干预/修改参数）"""
        unit = self.get_entry(unit_id)
        if not unit:
            return None

        # 可更新字段
        updatable = [
            'practical_ref', 'capital_allocation', 'entry_price',
            'current_price', 'stage', 'direction', 'confidence',
        ]
        for field in updatable:
            if field in data:
                setattr(unit, field, data[field])

        if 'practical_ref' in data:
            unit.practical_ref = data['practical_ref']
        if 'capital_allocation' in data and data['capital_allocation']:
            unit.capital_allocation = {**unit.capital_allocation, **data['capital_allocation']}
            if 'stop_loss_price' in data['capital_allocation']:
                unit.capital_allocation['stop_loss_price'] = data['capital_allocation']['stop_loss_price']
            if 'take_profit_levels' in data['capital_allocation']:
                unit.capital_allocation['take_profit_levels'] = data['capital_allocation']['take_profit_levels']

        unit.updated_at = datetime.now()
        db.session.commit()
        return unit

    def delete_entry(self, unit_id: str) -> bool:
        """删除复盘条目（软删除）"""
        unit = self.get_entry(unit_id)
        if not unit:
            return False
        unit.deleted_at = datetime.now()
        db.session.commit()
        return True

    # ────────────────────────────────────────────────
    # 账户管理
    # ────────────────────────────────────────────────

    def get_account(self) -> Optional[PlaybackAccount]:
        """获取复盘账户状态"""
        return PlaybackAccount.query.first()

    def reset_account(self, initial_capital: float = 1000000.0) -> PlaybackAccount:
        """重置复盘账户"""
        account = self.get_account()
        if not account:
            account = PlaybackAccount()
            db.session.add(account)

        account.initial_capital = initial_capital
        account.current_equity = initial_capital
        account.cash_balance = initial_capital
        account.position_value = 0.0
        account.total_realized_pnl = 0.0
        account.today_pnl = 0.0
        account.total_fees = 0.0
        account.daily_pnl_log = []
        account.peak_equity = initial_capital
        account.max_drawdown_pct = 0.0
        account.max_drawdown_date = None
        account.position_count = 0
        account.completed_count = 0
        account.updated_at = datetime.now()
        db.session.commit()

        # 同时清除所有复盘条目
        ReviewUnit.query.update({'deleted_at': datetime.now()})
        db.session.commit()

        return account

    # ────────────────────────────────────────────────
    # 统计概览
    # ────────────────────────────────────────────────

    def get_statistics(self) -> Dict:
        """获取统计概览（深度分析6区块数据）"""
        completed = ReviewUnit.query.filter_by(stage='completed', deleted_at=None).all()
        total_trades = len(completed)
        if total_trades == 0:
            return _empty_stats()

        # 胜率
        winners = [u for u in completed if (u.realized_pnl_pct or 0) > 0]
        win_rate = round(len(winners) / total_trades * 100, 1) if total_trades > 0 else 0

        # 平均盈亏比
        avg_win = sum(float(u.realized_pnl_pct or 0) for u in winners) / max(len(winners), 1)
        losers = [u for u in completed if (u.realized_pnl_pct or 0) <= 0]
        avg_loss = abs(sum(float(u.realized_pnl_pct or 0) for u in losers)) / max(len(losers), 1)
        avg_pnl_ratio = round(avg_win / max(avg_loss, 0.01), 1) if avg_loss > 0 else 0

        # 平均持有天数
        avg_holding = round(sum(u.holding_days or 0 for u in completed) / total_trades, 1)

        # P&L 分布
        pnl_dist = {'negative': 0, '0_5': 0, '5_10': 0, '10_15': 0, '15_plus': 0}
        for u in completed:
            pnl = float(u.realized_pnl_pct or 0)
            if pnl <= 0:
                pnl_dist['negative'] += 1
            elif pnl <= 5:
                pnl_dist['0_5'] += 1
            elif pnl <= 10:
                pnl_dist['5_10'] += 1
            elif pnl <= 15:
                pnl_dist['10_15'] += 1
            else:
                pnl_dist['15_plus'] += 1

        # 策略排名
        from collections import defaultdict
        strat_map = defaultdict(lambda: {'count': 0, 'total_pnl': 0.0, 'pnls': []})
        for u in completed:
            sc = u.strategy_config or {}
            dims = sc.get('dimensions', ['未知'])
            name = dims[0] if dims else '未知'
            pnl = float(u.realized_pnl_pct or 0)
            strat_map[name]['count'] += 1
            strat_map[name]['total_pnl'] += pnl
            strat_map[name]['pnls'].append(pnl)

        strategy_rankings = []
        for name, info in strat_map.items():
            wins = sum(1 for p in info['pnls'] if p > 0)
            wr = round(wins / info['count'] * 100, 1) if info['count'] > 0 else 0
            strategy_rankings.append({
                'strategy': name,
                'count': info['count'],
                'total_pnl_pct': round(info['total_pnl'], 2),
                'avg_pnl_pct': round(info['total_pnl'] / info['count'], 2) if info['count'] > 0 else 0,
                'win_rate': wr,
            })
        strategy_rankings.sort(key=lambda x: x['total_pnl_pct'], reverse=True)

        # 行业排名
        sector_map = defaultdict(lambda: {'total_pnl': 0.0, 'count': 0, 'pnls': []})
        for u in completed:
            pnl = float(u.realized_pnl_pct or 0)
            sector_map[u.sector or '未知']['total_pnl'] += pnl
            sector_map[u.sector or '未知']['count'] += 1
            sector_map[u.sector or '未知']['pnls'].append(pnl)
        sector_rankings = []
        for name, info in sector_map.items():
            wins = sum(1 for p in info['pnls'] if p > 0)
            sector_rankings.append({
                'sector': name,
                'total_pnl_pct': round(info['total_pnl'], 2),
                'avg_pnl_pct': round(info['total_pnl'] / info['count'], 2) if info['count'] > 0 else 0,
                'win_rate': round(wins / info['count'] * 100, 1) if info['count'] > 0 else 0,
            })
        sector_rankings.sort(key=lambda x: x['total_pnl_pct'], reverse=True)

        # 最佳/最差
        best = max(completed, key=lambda u: float(u.realized_pnl_pct or 0))
        worst = min(completed, key=lambda u: float(u.realized_pnl_pct or 0))

        # 月度
        monthly_map = defaultdict(lambda: {'count': 0, 'total_pnl': 0.0, 'pnls': []})
        for u in completed:
            exit_d = u.entry_date
            if exit_d:
                month = exit_d.strftime('%Y-%m')
                monthly_map[month]['count'] += 1
                monthly_map[month]['total_pnl'] += float(u.realized_pnl_pct or 0)
                monthly_map[month]['pnls'].append(float(u.realized_pnl_pct or 0))
        monthly = []
        for month, info in sorted(monthly_map.items()):
            wins = sum(1 for p in info['pnls'] if p > 0)
            monthly.append({
                'month': month,
                'count': info['count'],
                'total_pnl_pct': round(info['total_pnl'], 2),
                'win_rate': round(wins / info['count'] * 100, 1) if info['count'] > 0 else 0,
            })

        return {
            'total_trades': total_trades,
            'win_rate': win_rate,
            'avg_pnl_ratio': avg_pnl_ratio,
            'avg_holding_days': avg_holding,
            'pnl_distribution': pnl_dist,
            'strategy_rankings': strategy_rankings,
            'sector_rankings': sector_rankings,
            'best_trade': {
                'id': best.unit_id, 'name': best.name,
                'pnl_pct': float(best.realized_pnl_pct or 0),
            },
            'worst_trade': {
                'id': worst.unit_id, 'name': worst.name,
                'pnl_pct': float(worst.realized_pnl_pct or 0),
            },
            'monthly': monthly,
        }

    # ────────────────────────────────────────────────
    # 诊断报告
    # ────────────────────────────────────────────────

    def generate_report(self, unit_id: str, include_raw: bool = False) -> Optional[PlaybackReport]:
        """生成单个条目的九维诊断报告"""
        unit = self.get_entry(unit_id)
        if not unit:
            return None
        if unit.stage != 'completed':
            return None

        # 检查是否已存在
        existing = PlaybackReport.query.filter_by(unit_id=unit_id).first()
        if existing:
            return existing

        # 执行九维诊断
        dimensions, total_score = self._diagnose(unit)
        improvements = self._generate_improvements(dimensions, total_score)
        root_layer = self._find_root_layer(dimensions)

        # 生成报告ID
        today = datetime.now().strftime('%Y%m%d')
        count = PlaybackReport.query.filter(
            PlaybackReport.report_id.like(f'RR-{today}-%')
        ).count()
        report_id = f'RR-{today}-{count + 1:03d}'

        ds = {'overall_verdict': '盈利' if (unit.realized_pnl_pct or 0) > 0 else '亏损',
              'root_layer': root_layer,
              'diagnosis_confidence': round(total_score / 100, 1)}

        report = PlaybackReport(
            report_id=report_id,
            unit_id=unit_id,
            ts_code=unit.ts_code,
            name=unit.name,
            generated_at=datetime.now(),
            summary=f"{'✅' if (unit.realized_pnl_pct or 0) > 0 else '❌'} {unit.name}策略执行{'成功' if (unit.realized_pnl_pct or 0) > 0 else '未达预期'}。诊断根因定位在{root_layer}。",
            dimensions=dimensions,
            total_score=total_score,
            improvements=improvements,
            diagnostic_summary=ds,
            exit_analysis={
                'reason': unit.exit_reason,
                'timing': '合理',
            },
            capital_analysis={
                'allocation_verdict': '合理',
                'stop_loss_verdict': '合理',
            },
            scenario_match={
                'actual': 'A',
                'assessment': '实际走势符合盈利预期' if (unit.realized_pnl_pct or 0) > 0 else '实际走势弱于预期',
            },
            raw_data=unit.to_dict() if include_raw else None,
        )
        db.session.add(report)

        # 更新条目
        unit.has_report = True
        unit.report_id = report_id
        unit.review_analysis = {'dimensions': dimensions, 'total_score': total_score,
                                'root_layer': root_layer}

        db.session.commit()
        logger.info(f"诊断报告已生成: {report_id} for {unit_id}")
        return report

    def get_diagnosis_summary(self) -> Dict:
        """获取诊断汇总统计"""
        reports = PlaybackReport.query.all()
        total = len(reports)
        if total == 0:
            return {'total': 0, 'layer_distribution': {}, 'exit_layer_cross': {}}

        layer_dist = {f'Layer{i}': 0 for i in range(1, 6)}
        exit_cross = {}
        for r in reports:
            ds = r.diagnostic_summary or {}
            layer = ds.get('root_layer', 'Layer1')
            layer_dist[layer] = layer_dist.get(layer, 0) + 1

            ea = r.exit_analysis or {}
            reason = ea.get('reason', 'unknown')
            key = f'{reason}|{layer}'
            exit_cross[key] = exit_cross.get(key, 0) + 1

        return {
            'total': total,
            'layer_distribution': layer_dist,
            'exit_layer_cross': exit_cross,
        }

    # ────────────────────────────────────────────────
    # Phase 1: 模拟执行引擎（核心算法）
    # ────────────────────────────────────────────────

    def simulate_day(self, trade_date: str, market_data: Dict[str, Dict] = None) -> Dict:
        """每日模拟推进 — pending→holding→completed 全链条"""
        from datetime import datetime as dt
        current = dt.strptime(trade_date, '%Y-%m-%d').date()
        account = self.get_account()
        if not account:
            return {'status': 'no_account', 'events': 0}

        units = ReviewUnit.query.filter(
            ReviewUnit.deleted_at.is_(None),
            ReviewUnit.stage.in_(['pending', 'holding'])
        ).all()

        events_count = 0
        for unit in units:
            dd = (market_data or {}).get(unit.ts_code)
            if unit.stage == 'pending':
                result = self._process_pending(unit, current, dd)
                if result:
                    events_count += 1
            elif unit.stage == 'holding':
                result = self._process_holding(unit, account, current, dd)
                if result:
                    events_count += 1

        self._update_account_state(account, units, current)
        return {'status': 'ok', 'events': events_count, 'date': trade_date}

    def _process_pending(self, unit: ReviewUnit, current_date: date, daily_data: Dict = None) -> bool:
        """处理待实盘状态的条目"""
        if not unit.snapshot_date:
            return False
        days_since = (current_date - unit.snapshot_date).days
        if days_since > 30:
            unit.stage = 'completed'
            unit.exit_reason = 'time_stop'
            unit.stage_progress_pct = 100
            unit.realized_pnl_pct = 0
            unit.realized_pnl_amount = 0
            unit.events = (unit.events or []) + [{
                'date': current_date.isoformat(),
                'type': 'timeout',
                'desc': '超过30日未触发开仓条件，自动废弃',
                'severity': 'warning',
            }]
            unit.holding_days = 0
            logger.info(f"{unit.unit_id} 超时废弃")
            return True

        if daily_data and self._check_entry_condition(unit, daily_data):
            self._allocate_position(unit, daily_data, current_date)
            return True
        return False

    def _process_holding(self, unit: ReviewUnit, account: PlaybackAccount,
                         current_date: date, daily_data: Dict = None) -> bool:
        """处理持仓中的条目"""
        unit.holding_days = (unit.holding_days or 0) + 1
        if not daily_data:
            return False

        close_price = float(daily_data.get('close', 0))
        low_price = float(daily_data.get('low', close_price))
        high_price = float(daily_data.get('high', close_price))
        unit.current_price = close_price
        entry_p = float(unit.entry_price or 1)
        unit.unrealized_pnl_pct = round((close_price / entry_p - 1) * 100, 2)

        ca = unit.capital_allocation or {}
        sl_price = ca.get('stop_loss_price')
        tp_levels = ca.get('take_profit_levels', [])
        stage_pct = self._calc_stage_progress(unit, close_price)

        # 熔断检查
        if account.current_equity and account.initial_capital:
            dd_pct = (float(account.current_equity) - float(account.initial_capital)) / float(account.initial_capital)
            if dd_pct <= -0.02:
                self._close_position(unit, account, close_price, 'circuit_breaker', current_date)
                return True

        # 止损检查
        if sl_price and low_price <= float(sl_price):
            self._close_position(unit, account, float(sl_price), 'stop_loss_hit', current_date)
            return True

        # 止盈检查
        for i, tp in enumerate(tp_levels):
            if high_price >= float(tp):
                tier = 2 if i == 1 else 1
                self._close_position(unit, account, float(tp), f'take_profit_tier{tier}', current_date,
                                     is_full=(i == 1))
                return True

        # 信号反转
        direction = daily_data.get('direction', 0)
        if unit.direction == 'bullish' and direction < -2:
            self._close_position(unit, account, close_price, 'signal_reversal', current_date)
            return True

        # 超时平仓(60天)
        if unit.holding_days and unit.holding_days >= 60:
            self._close_position(unit, account, close_price, 'time_stop', current_date)
            return True

        unit.stage_progress_pct = stage_pct
        events = unit.events or []
        if events and events[-1].get('date') != current_date.isoformat():
            events.append({
                'date': current_date.isoformat(),
                'type': 'price_update',
                'desc': f"收盘价 {close_price:.2f}，浮动盈亏 {unit.unrealized_pnl_pct:+.2f}%",
                'severity': 'info',
            })
        unit.events = events
        return False

    def _allocate_position(self, unit: ReviewUnit, daily_data: Dict, entry_date: date):
        """基于Kelly公式+ATR的仓位分配"""
        entry_price = float(daily_data.get('close', 0))
        unit.entry_price = entry_price
        unit.entry_date = entry_date
        unit.stage = 'holding'
        unit.current_price = entry_price

        # 简单Kelly分配：默认5%风险/笔，仓位=总资金*5%/ATR
        confidence = float(unit.confidence or 0.75)
        kelly_pct = min(confidence * 0.1, 0.05)
        atr = daily_data.get('atr', entry_price * 0.02)

        account = self.get_account()
        alloc_capital = float(account.current_equity) * kelly_pct if account else 10000
        shares = int(alloc_capital / (entry_price * 1.0003))  # 扣手续费
        shares = max(shares, 100)
        position_val = round(shares * entry_price, 2)

        # 止损/止盈
        stop_loss = round(entry_price * (1 - 0.08), 2)
        take_profit_1 = round(entry_price * (1 + 0.15), 2)
        take_profit_2 = round(entry_price * (1 + 0.25), 2)

        # ATR调整：止损距 < ATR×1.5 → 仓位减半
        stop_dist = entry_price - stop_loss
        if stop_dist > 0 and atr > 0 and stop_dist < atr * 1.5:
            shares //= 2
            position_val = round(shares * entry_price, 2)

        fee = round(position_val * 0.00025, 2)  # 佣金万2.5
        unit.capital_allocation = {
            'allocated_capital': position_val,
            'shares': shares,
            'position_value': position_val,
            'stop_loss_price': stop_loss,
            'take_profit_levels': [take_profit_1, take_profit_2],
            'realized_pnl_amount': 0,
            'fee_paid': fee,
        }
        unit.stage_progress_pct = 10

        events = unit.events or []
        events.append({
            'date': entry_date.isoformat(),
            'type': 'entry',
            'desc': f'开仓条件满足，自动买入 {shares} 股，入场价 {entry_price:.2f}（含手续费万10）',
            'severity': 'info',
        })
        unit.events = events
        logger.info(f"{unit.unit_id} 开仓: {shares}股@{entry_price:.2f}")

    def _close_position(self, unit: ReviewUnit, account: PlaybackAccount,
                        exit_price: float, reason: str, close_date: date, is_full: bool = True):
        """平仓结算"""
        ca = unit.capital_allocation or {}
        shares = ca.get('shares', 0)
        entry_p = float(unit.entry_price or 1)
        pnl_amount = round((exit_price - entry_p) * shares, 2)
        pnl_pct = round((exit_price / entry_p - 1) * 100, 2)

        if reason.startswith('take_profit_tier1') and not is_full:
            pnl_amount = round(pnl_amount / 2, 2)
            pnl_pct = round(pnl_pct / 2, 2)

        fee = round(exit_price * shares * 0.00025, 2)  # 卖出佣金
        stamp_tax = round(exit_price * shares * 0.0005, 2) if reason != 'circuit_breaker' else 0

        unit.stage = 'completed'
        unit.exit_price = exit_price
        unit.exit_reason = reason
        unit.realized_pnl_pct = pnl_pct
        unit.realized_pnl_amount = pnl_amount
        unit.stage_progress_pct = 100
        unit.capital_allocation['realized_pnl_amount'] = pnl_amount
        unit.capital_allocation['fee_paid'] = (ca.get('fee_paid', 0) or 0) + fee + stamp_tax

        # 更新账户
        account.cash_balance = float(account.cash_balance) + exit_price * shares - fee - stamp_tax
        account.total_realized_pnl = float(account.total_realized_pnl) + pnl_amount
        account.total_fees = float(account.total_fees) + fee + stamp_tax
        account.position_count = max((account.position_count or 1) - 1, 0)
        account.completed_count = (account.completed_count or 0) + 1

        reason_label = self.EXIT_REASONS.get(reason, reason)
        events = unit.events or []
        events.append({
            'date': close_date.isoformat(),
            'type': 'exit',
            'desc': f'平仓: {reason_label}，出场价 {exit_price:.2f}，盈亏 {pnl_pct:+.2f}%',
            'severity': 'info',
        })
        unit.events = events
        logger.info(f"{unit.unit_id} 平仓: {reason} @ {exit_price:.2f}, P&L={pnl_pct:+.2f}%")

    def manual_close(self, unit_id: str) -> bool:
        """手动提前平仓"""
        unit = self.get_entry(unit_id)
        if not unit or unit.stage != 'holding':
            return False
        account = self.get_account()
        if not account:
            return False
        close_price = unit.current_price or float(unit.entry_price or 0)
        self._close_position(unit, account, close_price, 'manual_close', date.today())
        unit.has_report = False  # 手动平仓不生成报告
        db.session.commit()
        return True

    # ────────────────────────────────────────────────
    # 内部辅助方法
    # ────────────────────────────────────────────────

    @staticmethod
    def _check_entry_condition(unit: ReviewUnit, daily_data: Dict) -> bool:
        """检查开仓条件"""
        close = float(daily_data.get('close', 0))
        vol = float(daily_data.get('vol', 0))
        ma5 = float(daily_data.get('ma5', 0))
        ma20 = float(daily_data.get('ma20', 0))
        confidence = float(unit.confidence or 0.75)
        base = float(unit.base_price or 1)

        checks = 0
        # 量能条件
        if vol > 0 and ma5 > 0:
            if vol >= ma5 * 1.5:
                checks += 1
        # 均线条件
        if ma5 > 0 and ma20 > 0 and close > ma5 > ma20:
            checks += 1
        # 价格在基准附近
        if base > 0 and 0.95 * base <= close <= 1.15 * base:
            checks += 1
        # 置信度条件
        if confidence >= 0.7:
            checks += 1

        return checks >= 2

    @staticmethod
    def _calc_stage_progress(unit: ReviewUnit, current_price: float) -> float:
        """计算阶段进度百分比"""
        entry = float(unit.entry_price or 1)
        sl = unit.capital_allocation.get('stop_loss_price', entry * 0.92) if unit.capital_allocation else entry * 0.92
        tp = unit.capital_allocation.get('take_profit_levels', [entry * 1.15]) if unit.capital_allocation else [entry * 1.15]
        tp_price = float(tp[-1]) if isinstance(tp, list) and tp else entry * 1.15

        if current_price <= float(sl):
            return 95
        if current_price >= tp_price:
            return 90
        progress = (current_price - float(sl)) / (tp_price - float(sl)) * 80 + 10
        return round(min(max(progress, 10), 90), 1)

    @staticmethod
    def _diagnose(unit: ReviewUnit) -> Tuple[List, float]:
        """执行九维诊断分析"""
        is_profitable = (unit.realized_pnl_pct or 0) > 0
        pnl = abs(float(unit.realized_pnl_pct or 0))
        entry_q = 50 + min(pnl * 2, 40)
        exit_q = 50 + min(pnl * 3, 40)

        # 生成九维评分
        dimensions = [
            {'key': 'direction', 'label': '维度方向判断', 'score': round(65 + pnl * 1.5, 0), 'layer': 'Layer1'},
            {'key': 'conflict', 'label': '维度间冲突', 'score': round(60 + (1 if is_profitable else 0) * 20, 0), 'layer': 'Layer1'},
            {'key': 'verify', 'label': '交叉验证', 'score': round(55 + pnl * 2, 0), 'layer': 'Layer2'},
            {'key': 'arbitration', 'label': '仲裁方向', 'score': round(70 + pnl * 2, 0), 'layer': 'Layer3'},
            {'key': 'scenario', 'label': '情景推演', 'score': round(60 + pnl * 1.5, 0), 'layer': 'Layer3'},
            {'key': 'entry', 'label': '入场条件', 'score': round(entry_q, 0), 'layer': 'Layer4'},
            {'key': 'exit', 'label': '退出条件', 'score': round(exit_q, 0), 'layer': 'Layer4'},
            {'key': 'stop_tp', 'label': '止损/止盈', 'score': round(70 + (1 if is_profitable else 0) * 15, 0), 'layer': 'Layer5'},
            {'key': 'capital', 'label': '资金管理', 'score': round(65 + pnl * 2, 0), 'layer': 'Layer5'},
        ]
        for d in dimensions:
            d['score'] = min(max(d['score'], 20), 100)
        total_score = round(sum(d['score'] for d in dimensions) / 9, 0)
        return dimensions, total_score

    @staticmethod
    def _generate_improvements(dimensions: List, total_score: float) -> List:
        """生成改进建议"""
        low_dims = [d for d in dimensions if d['score'] < 60]
        if not low_dims:
            return [{'priority': 'LOW', 'category': '诊断结论', 'suggestion': '各维度表现良好，无需显著改进'}]

        improvements = []
        for d in low_dims:
            improvements.append({
                'priority': 'HIGH' if d['score'] < 45 else 'MEDIUM',
                'category': '诊断结论',
                'suggestion': f"{d['label']}得分 {d['score']:.0f}，需关注改进",
            })
        improvements.append({
            'priority': 'HIGH' if total_score < 60 else 'MEDIUM',
            'category': '诊断结论',
            'suggestion': f'根因定位：{low_dims[-1]["layer"]}，共{len(low_dims)}项维度需关注',
        })
        return improvements

    @staticmethod
    def _find_root_layer(dimensions: List) -> str:
        """定位根因层"""
        if not dimensions:
            return 'Layer1'
        min_dim = min(dimensions, key=lambda d: d['score'])
        return min_dim['layer']

    @staticmethod
    def _update_account_state(account: PlaybackAccount, units: List, current_date: date):
        """更新账户状态"""
        total_position = 0.0
        pos_count = 0
        for u in units:
            if u.stage == 'holding':
                current = float(u.current_price or 0)
                shares = (u.capital_allocation or {}).get('shares', 0)
                total_position += current * shares
                pos_count += 1

        equity = float(account.cash_balance or 0) + total_position

        daily_log = account.daily_pnl_log or []
        prev_equity = daily_log[-1]['equity'] if daily_log else float(account.initial_capital or 0)
        daily_pnl = round(equity - prev_equity, 2)

        daily_log.append({
            'date': current_date.isoformat(),
            'daily': daily_pnl,
            'cumulative': round(equity - float(account.initial_capital or 0), 2),
            'equity': equity,
            'positions': pos_count,
        })

        peak = max(float(account.peak_equity or 0), equity)
        dd_pct = round((equity - peak) / peak * 100, 2) if peak > 0 else 0

        account.current_equity = equity
        account.position_value = total_position
        account.today_pnl = daily_pnl
        account.peak_equity = peak
        account.position_count = pos_count
        account.daily_pnl_log = daily_log
        if dd_pct < float(account.max_drawdown_pct or 0):
            account.max_drawdown_pct = dd_pct
            account.max_drawdown_date = current_date
        account.updated_at = datetime.now()
        db.session.commit()

    @staticmethod
    def _parse_date(val) -> Optional[date]:
        if not val:
            return None
        if isinstance(val, date):
            return val
        if isinstance(val, str):
            try:
                return datetime.strptime(val[:10], '%Y-%m-%d').date()
            except ValueError:
                pass
        return None


def _empty_stats() -> Dict:
    return {
        'total_trades': 0, 'win_rate': 0, 'avg_pnl_ratio': 0, 'avg_holding_days': 0,
        'pnl_distribution': {'negative': 0, '0_5': 0, '5_10': 0, '10_15': 0, '15_plus': 0},
        'strategy_rankings': [], 'sector_rankings': [],
        'best_trade': None, 'worst_trade': None, 'monthly': [],
    }
