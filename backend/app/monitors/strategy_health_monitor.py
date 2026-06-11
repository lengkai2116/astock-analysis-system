"""
策略健康度监控

功能：
  1. 各信号类型 win_rate 变化趋势分析
  2. 胜率异常下降预警
  3. 样本量不足预警
  4. 输出周度健度报告摘要
"""
import logging
from typing import Dict, List, Optional
from datetime import date, timedelta

from app import db
from app.models.verification import SignalRecord

logger = logging.getLogger(__name__)
from app.services.alert_notifier import AlertNotifier

_notifier = AlertNotifier()


class StrategyHealthMonitor:
    """策略健康度监控器"""

    def __init__(self):
        self.thresholds = {
            'win_rate_5d_min': 0.45,       # 5日胜率最低阈值
            'win_rate_20d_min': 0.40,       # 20日胜率最低阈值
            'min_samples_per_type': 5,      # 每类信号最少样本量
            'win_rate_decline_warn': -0.10,  # 环比下降超过10%预警
            'sharpe_min': 0.3,              # 最小夏普比率
        }

    def check(self, lookback_days: int = 90) -> Dict:
        """
        执行健康度检查

        Args:
            lookback_days: 回看天数（默认90天）

        Returns:
            {
                'signal_stats': {signal_type: {samples, win_rate_5d, ...}},
                'alerts': [{'type': str, 'severity': 'WARN'|'ALERT', 'message': str}],
                'summary': str
            }
        """
        cutoff = date.today() - timedelta(days=lookback_days)
        alerts = []

        # 获取本周期已完成验证的信号
        records = SignalRecord.query.filter(
            SignalRecord.signal_date >= cutoff,
            SignalRecord.verification_status == 'completed'
        ).all()

        if not records:
            return {
                'signal_stats': {},
                'alerts': [{'type': 'NO_DATA', 'severity': 'WARN',
                            'message': f'近{lookback_days}天无已完成验证的信号数据'}],
                'summary': '数据不足'
            }

        # 按信号类型分组统计
        stats = self._group_stats(records)

        # 逐类型检查
        for sig_type, st in stats.items():
            # 样本量不足
            if st['samples'] < self.thresholds['min_samples_per_type']:
                alerts.append({
                    'type': 'LOW_SAMPLES',
                    'severity': 'WARN',
                    'message': f'{sig_type}: 样本量{st["samples"]}<{self.thresholds["min_samples_per_type"]}'
                })
                continue

            # 5日胜率过低
            if st.get('win_rate_5d', 1) < self.thresholds['win_rate_5d_min']:
                alerts.append({
                    'type': 'LOW_WIN_RATE',
                    'severity': 'ALERT' if st['win_rate_5d'] < 0.35 else 'WARN',
                    'message': f'{sig_type}: 5日胜率{st["win_rate_5d"]:.1%}<{self.thresholds["win_rate_5d_min"]:.0%}'
                })

            # 20日胜率过低
            if st.get('win_rate_20d', 1) < self.thresholds['win_rate_20d_min']:
                alerts.append({
                    'type': 'LOW_WIN_RATE_20D',
                    'severity': 'ALERT' if st['win_rate_20d'] < 0.30 else 'WARN',
                    'message': f'{sig_type}: 20日胜率{st["win_rate_20d"]:.1%}<{self.thresholds["win_rate_20d_min"]:.0%}'
                })

            # 夏普过低
            if st.get('sharpe_20d', 10) < self.thresholds['sharpe_min'] and st['samples'] >= 10:
                alerts.append({
                    'type': 'LOW_SHARPE',
                    'severity': 'WARN',
                    'message': f'{sig_type}: 夏普{st["sharpe_20d"]:.2f}<{self.thresholds["sharpe_min"]}'
                })

        # 汇总
        total_signals = sum(s['samples'] for s in stats.values())
        avg_win_5d = sum(s.get('win_rate_5d', 0) * s['samples'] for s in stats.values()) / max(total_signals, 1)
        avg_win_20d = sum(s.get('win_rate_20d', 0) * s['samples'] for s in stats.values()) / max(total_signals, 1)

        summary = (
            f"共{len(stats)}类信号{total_signals}条样本 | "
            f"平均5日胜率{avg_win_5d:.1%} | 20日胜率{avg_win_20d:.1%} | "
            f"{len(alerts)}条预警"
        )

        return {
            'signal_stats': stats,
            'alerts': alerts,
            'summary': summary,
            'check_date': date.today().isoformat(),
            'lookback_days': lookback_days,
        }

    def _group_stats(self, records) -> Dict[str, Dict]:
        """按信号类型分组统计"""
        groups = {}
        for rec in records:
            st = rec.signal_type
            if st not in groups:
                groups[st] = {'samples': 0, 'wins_5d': 0, 'wins_20d': 0,
                              'returns_5d': [], 'returns_20d': []}
            g = groups[st]
            g['samples'] += 1
            if rec.is_win_5d:
                g['wins_5d'] += 1
            if rec.is_win_20d:
                g['wins_20d'] += 1
            if rec.return_t5 is not None:
                g['returns_5d'].append(rec.return_t5)
            if rec.return_t20 is not None:
                g['returns_20d'].append(rec.return_t20)

        result = {}
        for st, g in groups.items():
            import numpy as np
            win_5d = g['wins_5d'] / max(g['samples'], 1)
            win_20d = g['wins_20d'] / max(g['samples'], 1)
            avg_ret_5d = float(np.mean(g['returns_5d'])) if g['returns_5d'] else 0
            avg_ret_20d = float(np.mean(g['returns_20d'])) if g['returns_20d'] else 0
            sharpe_20d = (float(np.mean(g['returns_20d'])) / max(float(np.std(g['returns_20d'])), 0.001)
                          * (252 ** 0.5)) if len(g['returns_20d']) >= 5 else 0

            result[st] = {
                'samples': g['samples'],
                'win_rate_5d': round(win_5d, 4),
                'win_rate_20d': round(win_20d, 4),
                'avg_return_5d': round(avg_ret_5d, 4),
                'avg_return_20d': round(avg_ret_20d, 4),
                'sharpe_20d': round(sharpe_20d, 4),
            }
        return result
