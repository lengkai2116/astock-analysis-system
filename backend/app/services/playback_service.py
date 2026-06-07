"""
PlaybackService — 回放复盘系统
===============================
实现 151-P3-1: 时间轴 + 速度控制 + 事件时间线

从历史数据中重建市场状态，支持按时间推进复盘。
"""

import logging
from datetime import datetime, timedelta
from typing import List, Optional, Dict, Callable, Generator
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)


@dataclass
class PlaybackEvent:
    """回放事件"""
    timestamp: str
    event_type: str       # price_change / signal / alert / trade
    title: str
    description: str = ""
    data: Dict = field(default_factory=dict)
    severity: str = "info"  # info / warning / critical

    def to_dict(self) -> Dict:
        return {
            'timestamp': self.timestamp,
            'event_type': self.event_type,
            'title': self.title,
            'description': self.description,
            'data': self.data,
            'severity': self.severity,
        }


@dataclass
class PlaybackSnapshot:
    """回放时间快照"""
    date: str
    kline: Dict                     # 当日K线
    signals: List[Dict] = field(default_factory=list)     # 当日信号
    events: List[PlaybackEvent] = field(default_factory=list)
    indicators: Dict = field(default_factory=dict)         # 技术指标值
    resonance: Dict = field(default_factory=dict)          # 共振评分
    total_value: float = 0.0        # 组合总价值
    cash: float = 0.0               # 现金
    positions: List[Dict] = field(default_factory=list)    # 持仓

    def to_dict(self) -> Dict:
        return {
            'date': self.date,
            'kline': self.kline,
            'signals': self.signals,
            'events': [e.to_dict() for e in self.events],
            'indicators': self.indicators,
            'resonance': self.resonance,
            'total_value': self.total_value,
            'cash': self.cash,
            'positions': self.positions,
        }


class PlaybackService:
    """
    回放复盘服务

    使用方式:
        service = PlaybackService()
        service.load(ts_code='000001.SZ', start='20260101', end='20260601')
        for snapshot in service.play(speed=2.0):
            print(snapshot.to_dict())
    """

    # 可用速度倍率
    SPEED_OPTIONS = [0.5, 1.0, 1.5, 2.0, 5.0, 10.0, 50.0]

    def __init__(self):
        self._data: List[PlaybackSnapshot] = []
        self._index = 0
        self._speed = 1.0
        self._events: List[PlaybackEvent] = []
        self._ts_code = ""
        self._is_playing = False
        self._total_dates = 0

    @property
    def progress(self) -> float:
        return self._index / max(self._total_dates, 1) * 100

    @property
    def speed(self) -> float:
        return self._speed

    @speed.setter
    def speed(self, val: float):
        if val in self.SPEED_OPTIONS:
            self._speed = val
        else:
            # 取最近的可用值
            self._speed = min(self.SPEED_OPTIONS, key=lambda x: abs(x - val))

    @property
    def is_playing(self) -> bool:
        return self._is_playing

    @property
    def current_date(self) -> str:
        if 0 <= self._index < len(self._data):
            return self._data[self._index].date
        return ""

    def load(self, ts_code: str, kline_data: List[Dict],
             signals: Dict[str, List[Dict]] = None,
             positions: List[Dict] = None) -> int:
        """
        加载回放数据

        Args:
            ts_code: 股票代码
            kline_data: K线数据列表 [{trade_date, open, high, low, close, vol}, ...]
            signals: 各策略信号 {strategy_name: [{date, direction, ...}, ...]}
            positions: 持仓历史 [{date, ts_code, shares, cost, price}, ...]

        Returns:
            加载的天数
        """
        self._ts_code = ts_code
        self._data = []
        self._events = []
        self._index = 0
        self._is_playing = False

        signal_map: Dict[str, list] = {}
        if signals:
            for strategy, sig_list in signals.items():
                for s in sig_list:
                    d = s.get('date', s.get('trade_date', ''))[:10]
                    if d not in signal_map:
                        signal_map[d] = []
                    signal_map[d].append({**s, 'strategy': strategy})

        position_map: Dict[str, list] = {}
        if positions:
            for p in positions:
                d = p.get('date', '')[:10]
                if d not in position_map:
                    position_map[d] = []
                position_map[d].append(p)

        for bar in kline_data:
            date_str = str(bar.get('trade_date', ''))[:10]
            if not date_str:
                continue

            daily_signals = signal_map.get(date_str, [])
            daily_positions = position_map.get(date_str, [])
            daily_events = self._detect_events(date_str, bar, daily_signals)

            snapshot = PlaybackSnapshot(
                date=date_str,
                kline=bar,
                signals=daily_signals,
                events=daily_events,
                positions=daily_positions,
            )
            self._data.append(snapshot)

        self._total_dates = len(self._data)
        self._events = [e for snap in self._data for e in snap.events]
        return self._total_dates

    def play(self) -> Generator[PlaybackSnapshot, None, None]:
        """播放回放，每次迭代返回下一日快照"""
        self._is_playing = True
        while self._index < len(self._data):
            snapshot = self._data[self._index]
            self._index += 1
            yield snapshot
        self._is_playing = False

    def seek(self, index: int) -> Optional[PlaybackSnapshot]:
        """跳转到指定索引"""
        if 0 <= index < len(self._data):
            self._index = index
            return self._data[index]
        return None

    def seek_to_date(self, date_str: str) -> Optional[PlaybackSnapshot]:
        """跳转到指定日期"""
        for i, snap in enumerate(self._data):
            if snap.date == date_str:
                self._index = i
                return snap
        return None

    def get_timeline(self) -> List[str]:
        """获取完整时间线"""
        return [s.date for s in self._data]

    def get_all_events(self) -> List[PlaybackEvent]:
        """获取所有事件"""
        return self._events

    def get_summary(self) -> Dict:
        """获取回放总结"""
        return {
            'ts_code': self._ts_code,
            'total_dates': self._total_dates,
            'total_events': len(self._events),
            'date_range': {
                'start': self._data[0].date if self._data else '',
                'end': self._data[-1].date if self._data else '',
            },
            'current_index': self._index,
            'progress': round(self.progress, 1),
        }

    def _detect_events(self, date_str: str, bar: Dict,
                       signals: List[Dict]) -> List[PlaybackEvent]:
        """从K线和信号中检测事件"""
        events = []

        # 价格变动事件
        pct = float(bar.get('pct_chg', bar.get('change', 0)))
        if abs(pct) >= 5:
            events.append(PlaybackEvent(
                timestamp=date_str,
                event_type='price_change',
                title=f"股价大幅{'上涨' if pct > 0 else '下跌'}",
                description=f"当日涨跌幅 {pct:+.2f}%",
                data={'pct_chg': pct},
                severity='critical' if abs(pct) >= 9 else 'warning',
            ))

        # 信号事件
        for sig in signals:
            direction = sig.get('direction', 'neutral')
            strategy = sig.get('strategy', sig.get('source', 'unknown'))
            events.append(PlaybackEvent(
                timestamp=date_str,
                event_type='signal',
                title=f"{strategy} 策略{'看多' if direction == 'bullish' else '看空' if direction == 'bearish' else '中性'}信号",
                description=sig.get('description', sig.get('name', '')),
                data=sig,
                severity='info',
            ))

        return events


# 快捷函数
def create_playback(ts_code: str, kline_data: List[Dict],
                    signals: Dict = None) -> PlaybackService:
    svc = PlaybackService()
    svc.load(ts_code, kline_data, signals)
    return svc
