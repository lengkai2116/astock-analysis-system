"""
缠论策略模块
实现完整的缠论分析功能，包括线段识别、中枢识别、背驰判断和买卖点识别
参考 CZSC 项目和缠论量化策略指南设计
"""
from typing import Dict, List, Optional, Any
from datetime import datetime
import pandas as pd
import numpy as np
from dataclasses import dataclass


@dataclass
class KLine:
    """K线数据结构"""
    idx: int
    open: float
    high: float
    low: float
    close: float
    date: Any
    volume: float = 0.0
    
    def __repr__(self):
        return f"KLine(idx={self.idx}, O={self.open:.2f}, H={self.high:.2f}, L={self.low:.2f}, C={self.close:.2f})"


@dataclass
class Fractal:
    """分型结构"""
    type: str  # 'top' or 'bottom'
    idx: int
    price: float
    date: Any
    kline: KLine = None
    
    def __repr__(self):
        return f"Fractal({self.type}, idx={self.idx}, price={self.price:.2f})"


@dataclass
class Stroke:
    """笔结构"""
    start_idx: int
    end_idx: int
    start_price: float
    end_price: float
    start_date: Any
    end_date: Any
    direction: str  # 'up' or 'down'
    high: float = None
    low: float = None
    
    def __repr__(self):
        return f"Stroke({self.direction}, {self.start_idx}->{self.end_idx}, {self.start_price:.2f}->{self.end_price:.2f})"
    
    @property
    def amplitude(self):
        """笔的幅度"""
        return abs(self.end_price - self.start_price)


@dataclass
class Segment:
    """线段结构"""
    start_idx: int
    end_idx: int
    start_price: float
    end_price: float
    start_date: Any
    end_date: Any
    direction: str  # 'up' or 'down'
    strokes: List[Stroke] = None
    high: float = None
    low: float = None
    
    def __repr__(self):
        return f"Segment({self.direction}, {self.start_idx}->{self.end_idx}, {self.start_price:.2f}->{self.end_price:.2f})"
    
    @property
    def amplitude(self):
        """线段的幅度"""
        return abs(self.end_price - self.start_price)
    
    @property
    def range(self):
        """线段的高低点范围"""
        return {
            'high': self.high or max(self.start_price, self.end_price),
            'low': self.low or min(self.start_price, self.end_price)
        }


@dataclass
class Zhongshu:
    """中枢结构"""
    start_idx: int
    end_idx: int
    start_date: Any
    end_date: Any
    high: float  # 中枢区间高点
    low: float   # 中枢区间低点
    center: float = None  # 中枢中心
    direction: str = None  # 中枢方向
    segments: List[Segment] = None  # 构成中枢的线段
    range_width: float = None  # 中枢宽度
    
    def __post_init__(self):
        if self.center is None:
            self.center = (self.high + self.low) / 2
        if self.range_width is None:
            self.range_width = self.high - self.low
    
    def __repr__(self):
        return f"Zhongshu({self.direction}, [{self.low:.2f}, {self.high:.2f}], center={self.center:.2f})"
    
    def contains_price(self, price: float) -> bool:
        """判断价格是否在中枢区间内"""
        return self.low <= price <= self.high
    
    def is_above(self, price: float) -> bool:
        """判断价格是否在中枢上方"""
        return price > self.high
    
    def is_below(self, price: float) -> bool:
        """判断价格是否在中枢下方"""
        return price < self.low


@dataclass
class Divergence:
    """背驰结构"""
    type: str  # 'trend', 'consolidation', 'zhongshu'
    direction: str  # 'up' or 'down'
    confidence: float
    position: Dict = None
    details: Dict = None
    
    def __repr__(self):
        return f"Divergence({self.type}, {self.direction}, confidence={self.confidence:.2f})"


@dataclass
class BuySellPoint:
    """买卖点结构"""
    type: str  # 'first_buy', 'second_buy', 'third_buy', 'first_sell', 'second_sell', 'third_sell'
    confidence: float
    position: Dict  # {'idx', 'price', 'date'}
    reason: str
    zhongshu: Zhongshu = None  # 相关的中枢
    
    def __repr__(self):
        return f"BuySellPoint({self.type}, confidence={self.confidence:.2f}, price={self.position.get('price', 0):.2f})"


class KLineMerger:
    """K线包含关系处理"""
    
    @staticmethod
    def is_contained(k1: KLine, k2: KLine) -> bool:
        """检查两根K线是否有包含关系"""
        return (k2.high <= k1.high and k2.low >= k1.low) or \
               (k1.high <= k2.high and k1.low >= k2.low)
    
    @staticmethod
    def merge(klines: List[KLine]) -> List[KLine]:
        """
        处理K线包含关系
        
        Args:
            klines: 原始K线列表
        
        Returns:
            处理后的无包含K线列表
        """
        if len(klines) < 2:
            return klines
        
        result = []
        direction = None  # 'up' or 'down'
        
        for i in range(len(klines)):
            if i == 0:
                result.append(klines[0])
                continue
            
            current = klines[i]
            prev = result[-1]
            
            # 确定方向
            if direction is None:
                if current.high > prev.high:
                    direction = 'up'
                else:
                    direction = 'down'
            
            # 检查包含关系
            if KLineMerger.is_contained(prev, current):
                # 合并
                if direction == 'up':
                    new_high = max(prev.high, current.high)
                    new_low = max(prev.low, current.low)
                else:
                    new_high = min(prev.high, current.high)
                    new_low = min(prev.low, current.low)
                
                merged = KLine(
                    idx=prev.idx,
                    open=prev.open,
                    high=new_high,
                    low=new_low,
                    close=current.close,
                    date=current.date,
                    volume=prev.volume + current.volume
                )
                result[-1] = merged
            else:
                result.append(current)
                # 更新方向
                if current.high > prev.high:
                    direction = 'up'
                else:
                    direction = 'down'
        
        return result


class FractalDetector:
    """分型识别器"""
    
    @staticmethod
    def detect(klines: List[KLine]) -> List[Fractal]:
        """
        识别顶底分型
        
        Args:
            klines: 无包含K线列表
        
        Returns:
            分型列表
        """
        fractals = []
        
        for i in range(1, len(klines) - 1):
            prev = klines[i - 1]
            curr = klines[i]
            next_k = klines[i + 1]
            
            # 顶分型：中间高
            if (curr.high > prev.high and curr.high > next_k.high and
                curr.low > prev.low and curr.low > next_k.low):
                fractals.append(Fractal(
                    type='top',
                    idx=curr.idx,
                    price=curr.high,
                    date=curr.date,
                    kline=curr
                ))
            
            # 底分型：中间低
            if (curr.low < prev.low and curr.low < next_k.low and
                curr.high < prev.high and curr.high < next_k.high):
                fractals.append(Fractal(
                    type='bottom',
                    idx=curr.idx,
                    price=curr.low,
                    date=curr.date,
                    kline=curr
                ))
        
        return fractals


class StrokeBuilder:
    """笔构建器"""
    
    def __init__(self, min_klines: int = 3):
        """
        Args:
            min_klines: 笔包含的最少K线数（顶底分型之间）
        """
        self.min_klines = min_klines
    
    def build(self, fractals: List[Fractal]) -> List[Stroke]:
        """
        从分型构建笔
        
        Args:
            fractals: 分型列表
        
        Returns:
            笔列表
        """
        strokes = []
        
        i = 0
        while i < len(fractals) - 1:
            f1 = fractals[i]
            f2 = fractals[i + 1]
            
            # 确保分型交替（顶-底或底-顶）
            if f1.type == f2.type:
                i += 1
                continue
            
            # 检查间距（至少包含min_klines根独立K线）
            k_count = f2.idx - f1.idx
            if k_count < self.min_klines:
                i += 1
                continue
            
            # 检查方向和有效性
            valid = False
            if f1.type == 'bottom' and f2.type == 'top':
                # 向上笔：顶 > 底
                if f2.price > f1.price:
                    valid = True
                    direction = 'up'
            elif f1.type == 'top' and f2.type == 'bottom':
                # 向下笔：顶 > 底
                if f1.price > f2.price:
                    valid = True
                    direction = 'down'
            
            if valid:
                # 计算笔的高低点
                if direction == 'up':
                    # 向上笔：起点是底分型价格，终点是顶分型价格
                    high = f2.price
                    low = f1.price
                else:
                    # 向下笔：起点是顶分型价格，终点是底分型价格
                    high = f1.price
                    low = f2.price
                
                strokes.append(Stroke(
                    start_idx=f1.idx,
                    end_idx=f2.idx,
                    start_price=f1.price,
                    end_price=f2.price,
                    start_date=f1.date,
                    end_date=f2.date,
                    direction=direction,
                    high=high,
                    low=low
                ))
                i += 2
            else:
                i += 1
        
        return strokes


class SegmentAnalyzer:
    """线段分析器"""
    
    def __init__(self, min_stroke_count: int = 3):
        """
        Args:
            min_stroke_count: 构成线段的最少笔数
        """
        self.min_stroke_count = min_stroke_count
    
    def build(self, strokes: List[Stroke]) -> List[Segment]:
        """
        从笔构建线段
        
        线段定义：
        - 至少由 self.min_stroke_count 笔构成
        - 三笔之间存在重叠
        - 方向交替
        
        Args:
            strokes: 笔列表
        
        Returns:
            线段列表
        """
        segments = []
        
        i = 0
        while i <= len(strokes) - self.min_stroke_count:
            stroke1 = strokes[i]
            stroke2 = strokes[i + 1]
            stroke3 = strokes[i + 2]
            
            # 检查是否构成线段
            if self._is_valid_segment(stroke1, stroke2, stroke3):
                segment = self._create_segment(stroke1, stroke2, stroke3)
                segments.append(segment)
                i += 3  # 线段至少由3笔构成
            else:
                i += 1
        
        return segments
    
    def _is_valid_segment(self, s1: Stroke, s2: Stroke, s3: Stroke) -> bool:
        """判断三笔是否构成线段"""
        # 方向检查：必须交替
        if s1.direction == s2.direction or s2.direction == s3.direction:
            return False
        
        # 重叠检查：三笔必须有重叠区域
        if not self._has_overlap(s1, s2, s3):
            return False
        
        return True
    
    def _has_overlap(self, s1: Stroke, s2: Stroke, s3: Stroke) -> bool:
        """
        检查三笔是否有重叠
        
        对于上升线段：笔1向上，笔2向下，笔3向上
        需要笔2的低点高于笔1的起点，且笔3的高点高于笔2的起点
        
        对于下降线段：笔1向下，笔2向上，笔3向下
        需要笔2的高点低于笔1的起点，且笔3的低点低于笔2的起点
        """
        if s1.direction == 'up':
            # 上升线段：检查重叠
            # 笔2的低点应该高于笔1的起点
            overlap_low = max(s1.start_price, s2.low)
            overlap_high = min(s3.end_price, s2.high)
            return overlap_low <= overlap_high
        else:
            # 下降线段
            overlap_low = max(s2.low, s3.start_price)
            overlap_high = min(s1.start_price, s2.high)
            return overlap_low <= overlap_high
    
    def _create_segment(self, s1: Stroke, s2: Stroke, s3: Stroke) -> Segment:
        """创建线段结构"""
        if s1.direction == 'up':
            direction = 'up'
            start_price = s1.start_price
            end_price = s3.end_price
            high = max(s1.end_price, s3.high or s3.end_price)
            low = s1.start_price
        else:
            direction = 'down'
            start_price = s1.start_price
            end_price = s3.end_price
            high = s1.start_price
            low = min(s1.end_price, s3.low or s3.end_price)
        
        return Segment(
            start_idx=s1.start_idx,
            end_idx=s3.end_idx,
            start_price=start_price,
            end_price=end_price,
            start_date=s1.start_date,
            end_date=s3.end_date,
            direction=direction,
            strokes=[s1, s2, s3],
            high=high,
            low=low
        )


class ZhongshuAnalyzer:
    """中枢分析器"""
    
    def __init__(self, min_segment_count: int = 3):
        """
        Args:
            min_segment_count: 构成中枢的最少线段数
        """
        self.min_segment_count = min_segment_count
    
    def find(self, segments: List[Segment]) -> List[Zhongshu]:
        """
        识别中枢
        
        中枢定义：
        - 由至少3段构成
        - 三段存在重叠区域
        
        Args:
            segments: 线段列表
        
        Returns:
            中枢列表
        """
        zhongshu_list = []
        
        i = 0
        while i <= len(segments) - self.min_segment_count:
            seg1 = segments[i]
            seg2 = segments[i + 1]
            seg3 = segments[i + 2]
            
            # 检查是否构成中枢
            overlap = self._calculate_overlap(seg1, seg2, seg3)
            if overlap is not None:
                zhongshu = self._create_zhongshu(seg1, seg2, seg3, overlap)
                zhongshu_list.append(zhongshu)
                i += 3  # 中枢至少由3段构成
            else:
                i += 1
        
        return zhongshu_list
    
    def _calculate_overlap(self, seg1: Segment, seg2: Segment, seg3: Segment) -> Optional[tuple]:
        """
        计算三段的重叠区间
        
        Returns:
            (low, high) or None if no overlap
        """
        # 获取三段的波动区间
        ranges = [seg1.range, seg2.range, seg3.range]
        
        # 简化：计算所有候选区间的重叠部分
        overlap_low = max(r['low'] for r in ranges)
        overlap_high = min(r['high'] for r in ranges)
        
        if overlap_low <= overlap_high:
            return (overlap_low, overlap_high)
        
        return None
    
    def _create_zhongshu(self, seg1: Segment, seg2: Segment, seg3: Segment, 
                        overlap: tuple) -> Zhongshu:
        """创建中枢结构"""
        low, high = overlap
        
        return Zhongshu(
            start_idx=seg1.start_idx,
            end_idx=seg3.end_idx,
            start_date=seg1.start_date,
            end_date=seg3.end_date,
            high=high,
            low=low,
            center=(high + low) / 2,
            direction=seg1.direction,
            segments=[seg1, seg2, seg3],
            range_width=high - low
        )


class DivergenceDetector:
    """背驰检测器"""
    
    def __init__(self, lookback_period: int = 60):
        """
        Args:
            lookback_period: 回看周期
        """
        self.lookback_period = lookback_period
    
    def detect(self, strokes: List[Stroke], 
              zhongshu_list: List[Zhongshu] = None,
              volume: pd.Series = None) -> Optional[Divergence]:
        """
        检测背驰
        
        背驰类型：
        1. 趋势背驰：创新高/低后，力度明显减弱
        2. 盘整背驰：回调力度大于离开力度
        3. 中枢破坏：离开中枢的力度小于返回力度
        
        Args:
            strokes: 笔列表
            zhongshu_list: 中枢列表
            volume: 成交量数据
        
        Returns:
            背驰信息或None
        """
        if len(strokes) < 4:
            return None
        
        zhongshu_list = zhongshu_list or []
        
        # 检测趋势背驰
        trend_div = self._detect_trend_divergence(strokes)
        if trend_div:
            return trend_div
        
        # 检测盘整背驰
        consolid_div = self._detect_consolidation_divergence(strokes)
        if consolid_div:
            return consolid_div
        
        # 检测中枢破坏
        if zhongshu_list:
            zhongshu_div = self._detect_zhongshu_divergence(strokes, zhongshu_list)
            if zhongshu_div:
                return zhongshu_div
        
        return None
    
    def _detect_trend_divergence(self, strokes: List[Stroke]) -> Optional[Divergence]:
        """
        检测趋势背驰
        
        原理：创新高/低后，力度明显减弱
        """
        if len(strokes) < 4:
            return None
        
        # 获取最近的笔（方向交替）
        recent_up = [s for s in strokes if s.direction == 'up']
        recent_down = [s for s in strokes if s.direction == 'down']
        
        if len(recent_up) < 2 or len(recent_down) < 2:
            return None
        
        # 检查上涨趋势背驰
        last_up = recent_up[-1]
        prev_up = recent_up[-2]
        
        if last_up.end_price > prev_up.end_price:
            # 价格创新高
            current_amp = last_up.amplitude
            prev_amp = prev_up.amplitude
            
            # 力度明显减弱
            if current_amp < prev_amp * 0.8:
                return Divergence(
                    type='trend',
                    direction='up',
                    confidence=0.8,
                    position={'idx': last_up.end_idx, 'price': last_up.end_price},
                    details={
                        'current_amplitude': current_amp,
                        'prev_amplitude': prev_amp,
                        'strength_ratio': current_amp / prev_amp
                    }
                )
        
        # 检查下跌趋势背驰
        last_down = recent_down[-1]
        prev_down = recent_down[-2]
        
        if last_down.end_price < prev_down.end_price:
            # 价格创新低
            current_amp = last_down.amplitude
            prev_amp = prev_down.amplitude
            
            # 力度明显减弱
            if current_amp < prev_amp * 0.8:
                return Divergence(
                    type='trend',
                    direction='down',
                    confidence=0.8,
                    position={'idx': last_down.end_idx, 'price': last_down.end_price},
                    details={
                        'current_amplitude': current_amp,
                        'prev_amplitude': prev_amp,
                        'strength_ratio': current_amp / prev_amp
                    }
                )
        
        return None
    
    def _detect_consolidation_divergence(self, strokes: List[Stroke]) -> Optional[Divergence]:
        """
        检测盘整背驰
        
        原理：回调力度大于离开力度
        """
        if len(strokes) < 4:
            return None
        
        # 获取最后两笔
        last_stroke = strokes[-1]
        prev_stroke = strokes[-2]
        
        # 检查方向
        if last_stroke.direction != prev_stroke.direction:
            # 如果最后一笔是下跌，检查回调是否背驰
            if last_stroke.direction == 'down':
                # 下跌幅度
                down_amp = abs(last_stroke.end_price - last_stroke.start_price)
                # 上一笔上涨幅度
                up_amp = abs(prev_stroke.end_price - prev_stroke.start_price)
                
                # 回调幅度大于离开幅度 = 背驰
                if down_amp > up_amp * 1.1:
                    return Divergence(
                        type='consolidation',
                        direction='up',  # 底背驰，准备上涨
                        confidence=0.7,
                        position={'idx': last_stroke.end_idx, 'price': last_stroke.end_price},
                        details={
                            'down_amplitude': down_amp,
                            'prev_up_amplitude': up_amp,
                            'ratio': down_amp / up_amp
                        }
                    )
            
            # 如果最后一笔是上涨，检查反弹是否背驰
            elif last_stroke.direction == 'up':
                up_amp = abs(last_stroke.end_price - last_stroke.start_price)
                down_amp = abs(prev_stroke.end_price - prev_stroke.start_price)
                
                if up_amp > down_amp * 1.1:
                    return Divergence(
                        type='consolidation',
                        direction='down',  # 顶背驰，准备下跌
                        confidence=0.7,
                        position={'idx': last_stroke.end_idx, 'price': last_stroke.end_price},
                        details={
                            'up_amplitude': up_amp,
                            'prev_down_amplitude': down_amp,
                            'ratio': up_amp / down_amp
                        }
                    )
        
        return None
    
    def _detect_zhongshu_divergence(self, strokes: List[Stroke],
                                    zhongshu_list: List[Zhongshu]) -> Optional[Divergence]:
        """
        检测中枢破坏背驰
        
        原理：离开中枢的力度小于返回的力度
        """
        if not zhongshu_list or len(strokes) < 4:
            return None
        
        # 获取最近的中枢
        latest_zhongshu = zhongshu_list[-1]
        
        # 检查最近的笔是否离开中枢
        if len(strokes) >= 2:
            last_stroke = strokes[-1]
            prev_stroke = strokes[-2]
            
            # 如果最后一笔是上涨
            if last_stroke.direction == 'up' and prev_stroke.direction == 'down':
                # 检查是否离开中枢
                if latest_zhongshu.is_above(last_stroke.end_price):
                    # 离开中枢上方，检查回调是否回到中枢
                    if latest_zhongshu.contains_price(prev_stroke.end_price):
                        return Divergence(
                            type='zhongshu',
                            direction='down',
                            confidence=0.6,
                            position={'idx': last_stroke.end_idx, 'price': last_stroke.end_price},
                            details={'zhongshu': str(latest_zhongshu)}
                        )
        
        return None


class BuySellPointDetector:
    """买卖点检测器"""
    
    def __init__(self, min_confidence: float = 0.6):
        """
        Args:
            min_confidence: 最小置信度
        """
        self.min_confidence = min_confidence
    
    def find(self, strokes: List[Stroke],
             zhongshu_list: List[Zhongshu],
             divergence: Divergence = None) -> tuple:
        """
        识别买卖点
        
        Args:
            strokes: 笔列表
            zhongshu_list: 中枢列表
            divergence: 背驰信息
        
        Returns:
            (buy_points, sell_points)
        """
        buy_points = []
        sell_points = []
        
        # 第一类买卖点：基于背驰
        if divergence:
            if divergence.direction == 'up':
                buy_points.append(BuySellPoint(
                    type='first_buy',
                    confidence=divergence.confidence,
                    position=divergence.position,
                    reason=f'下跌趋势背驰，{divergence.type}类型'
                ))
            else:
                sell_points.append(BuySellPoint(
                    type='first_sell',
                    confidence=divergence.confidence,
                    position=divergence.position,
                    reason=f'上涨趋势背驰，{divergence.type}类型'
                ))
        
        # 第二类买卖点：回调不创新低/高
        second_points = self._find_second_points(strokes, buy_points, sell_points)
        buy_points.extend(second_points['buy'])
        sell_points.extend(second_points['sell'])
        
        # 第三类买卖点：不进入中枢
        if zhongshu_list:
            third_points = self._find_third_points(strokes, zhongshu_list)
            buy_points.extend(third_points['buy'])
            sell_points.extend(third_points['sell'])
        
        # 过滤低置信度
        buy_points = [p for p in buy_points if p.confidence >= self.min_confidence]
        sell_points = [p for p in sell_points if p.confidence >= self.min_confidence]
        
        return buy_points, sell_points
    
    def _find_second_points(self, strokes: List[Stroke],
                           existing_buy: List[BuySellPoint],
                           existing_sell: List[BuySellPoint]) -> Dict[str, List]:
        """
        识别第二类买卖点
        
        第二类买点：第一类买点后上涨，回调不创新低
        第二类卖点：第一类卖点后下跌，反弹不创新高
        """
        second_buy = []
        second_sell = []
        
        # 检查是否有第一类买点后的回调
        if existing_buy:
            first_buy = existing_buy[0]
            first_buy_idx = first_buy.position.get('idx', 0)
            first_buy_price = first_buy.position.get('price', 0)
            
            # 查找后续的上涨和回调
            for i, stroke in enumerate(strokes):
                if stroke.start_idx <= first_buy_idx:
                    continue
                
                if stroke.direction == 'up' and i < len(strokes) - 1:
                    # 检查回调是否不创新低
                    next_stroke = strokes[i + 1]
                    if next_stroke.direction == 'down':
                        # 回调低点高于第一类买点 = 第二类买点
                        if next_stroke.end_price > first_buy_price:
                            second_buy.append(BuySellPoint(
                                type='second_buy',
                                confidence=0.7,
                                position={
                                    'idx': next_stroke.end_idx,
                                    'price': next_stroke.end_price,
                                    'date': next_stroke.end_date
                                },
                                reason='回调不创新低'
                            ))
        
        # 第二类卖点（类似逻辑）
        if existing_sell:
            first_sell = existing_sell[0]
            first_sell_idx = first_sell.position.get('idx', 0)
            first_sell_price = first_sell.position.get('price', 0)
            
            for i, stroke in enumerate(strokes):
                if stroke.start_idx <= first_sell_idx:
                    continue
                
                if stroke.direction == 'down' and i < len(strokes) - 1:
                    next_stroke = strokes[i + 1]
                    if next_stroke.direction == 'up':
                        if next_stroke.end_price < first_sell_price:
                            second_sell.append(BuySellPoint(
                                type='second_sell',
                                confidence=0.7,
                                position={
                                    'idx': next_stroke.end_idx,
                                    'price': next_stroke.end_price,
                                    'date': next_stroke.end_date
                                },
                                reason='反弹不创新高'
                            ))
        
        return {'buy': second_buy, 'sell': second_sell}
    
    def _find_third_points(self, strokes: List[Stroke],
                          zhongshu_list: List[Zhongshu]) -> Dict[str, List]:
        """
        识别第三类买卖点
        
        第三类买点：上涨回调不进入中枢
        第三类卖点：下跌反弹不进入中枢
        """
        third_buy = []
        third_sell = []
        
        if not zhongshu_list:
            return {'buy': third_buy, 'sell': third_sell}
        
        latest_zhongshu = zhongshu_list[-1]
        
        for i, stroke in enumerate(strokes[:-1]):
            # 第三类买点：上涨后回调
            if stroke.direction == 'up' and i < len(strokes) - 1:
                next_stroke = strokes[i + 1]
                if next_stroke.direction == 'down':
                    # 回调低点在中枢上方 = 第三类买点
                    if latest_zhongshu.is_above(next_stroke.end_price):
                        third_buy.append(BuySellPoint(
                            type='third_buy',
                            confidence=0.6,
                            position={
                                'idx': next_stroke.end_idx,
                                'price': next_stroke.end_price,
                                'date': next_stroke.end_date
                            },
                            reason=f'回调不进入中枢(中枢区间:[{latest_zhongshu.low:.2f}, {latest_zhongshu.high:.2f}])',
                            zhongshu=latest_zhongshu
                        ))
            
            # 第三类卖点：下跌后反弹
            elif stroke.direction == 'down' and i < len(strokes) - 1:
                next_stroke = strokes[i + 1]
                if next_stroke.direction == 'up':
                    # 反弹高点在中枢下方 = 第三类卖点
                    if latest_zhongshu.is_below(next_stroke.end_price):
                        third_sell.append(BuySellPoint(
                            type='third_sell',
                            confidence=0.6,
                            position={
                                'idx': next_stroke.end_idx,
                                'price': next_stroke.end_price,
                                'date': next_stroke.end_date
                            },
                            reason=f'反弹不进入中枢(中枢区间:[{latest_zhongshu.low:.2f}, {latest_zhongshu.high:.2f}])',
                            zhongshu=latest_zhongshu
                        ))
        
        return {'buy': third_buy, 'sell': third_sell}


class ChanlunAnalyzer:
    """
    完整缠论分析器
    
    整合所有缠论组件，提供完整的分析流程
    """
    
    def __init__(self, config: Dict = None):
        """
        Args:
            config: 配置参数
        """
        self.config = config or {}
        
        # 初始化各组件
        self.kline_merger = KLineMerger()
        self.fractal_detector = FractalDetector()
        self.stroke_builder = StrokeBuilder(
            min_klines=self.config.get('min_klines', 3)
        )
        self.segment_analyzer = SegmentAnalyzer(
            min_stroke_count=self.config.get('min_stroke_count', 3)
        )
        self.zhongshu_analyzer = ZhongshuAnalyzer(
            min_segment_count=self.config.get('min_segment_count', 3)
        )
        self.divergence_detector = DivergenceDetector(
            lookback_period=self.config.get('lookback_period', 60)
        )
        self.buy_sell_detector = BuySellPointDetector(
            min_confidence=self.config.get('min_confidence', 0.6)
        )
        
        # 分析结果
        self.klines = []
        self.fractals = []
        self.strokes = []
        self.segments = []
        self.zhongshu_list = []
        self.divergence = None
        self.buy_points = []
        self.sell_points = []
    
    @staticmethod
    def _default_config() -> Dict:
        """默认配置"""
        return {
            'min_klines': 3,  # 笔包含的最少K线数
            'min_stroke_count': 3,  # 构成线段的最少笔数
            'min_segment_count': 3,  # 构成中枢的最少线段数
            'lookback_period': 60,  # 回看周期
            'min_confidence': 0.6  # 最小置信度
        }
    
    def analyze(self, df: pd.DataFrame) -> Dict:
        """
        完整缠论分析流程
        
        Args:
            df: OHLCV数据，列名：open, high, low, close, volume, trade_date
        
        Returns:
            完整分析结果
        """
        # 1. 数据预处理
        self._preprocess(df)
        
        if len(self.klines) < 30:
            return {'error': '数据不足，需要至少30根K线'}
        
        # 2. 包含处理
        klines_no_contain = self.kline_merger.merge(self.klines)
        
        # 3. 分型识别
        self.fractals = self.fractal_detector.detect(klines_no_contain)
        
        if len(self.fractals) < 4:
            return {'error': '分型不足，无法构建笔'}
        
        # 4. 笔构建
        self.strokes = self.stroke_builder.build(self.fractals)
        
        if len(self.strokes) < 3:
            return {'error': '笔不足，无法构建线段'}
        
        # 5. 线段识别
        self.segments = self.segment_analyzer.build(self.strokes)
        
        # 6. 中枢识别
        if len(self.segments) >= 3:
            self.zhongshu_list = self.zhongshu_analyzer.find(self.segments)
        
        # 7. 背驰判断
        self.divergence = self.divergence_detector.detect(
            self.strokes, 
            self.zhongshu_list
        )
        
        # 8. 买卖点识别
        self.buy_points, self.sell_points = self.buy_sell_detector.find(
            self.strokes,
            self.zhongshu_list,
            self.divergence
        )
        
        return self._generate_result()
    
    def _preprocess(self, df: pd.DataFrame):
        """数据预处理"""
        self.klines = []
        
        for idx, row in df.iterrows():
            kl = KLine(
                idx=idx,
                open=row['open'],
                high=row['high'],
                low=row['low'],
                close=row['close'],
                date=row.get('trade_date', idx),
                volume=row.get('volume', 0)
            )
            self.klines.append(kl)
    
    def _generate_result(self) -> Dict:
        """生成分析结果"""
        return {
            'success': True,
            'fractals': self.fractals,
            'strokes': self.strokes,
            'segments': self.segments if self.segments else [],
            'zhongshu': self.zhongshu_list,
            'divergence': self.divergence,
            'buy_points': self.buy_points,
            'sell_points': self.sell_points,
            'trend': self._determine_trend(),
            'summary': self._generate_summary()
        }
    
    def _determine_trend(self) -> str:
        """判断当前趋势"""
        if not self.segments:
            return 'unknown'
        
        last_segment = self.segments[-1]
        return last_segment.direction
    
    def _generate_summary(self) -> Dict:
        """生成分析摘要"""
        summary = {
            'total_klines': len(self.klines),
            'total_fractals': len(self.fractals),
            'total_strokes': len(self.strokes),
            'total_segments': len(self.segments),
            'total_zhongshu': len(self.zhongshu_list),
            'current_trend': self._determine_trend(),
            'has_divergence': self.divergence is not None,
            'divergence_type': self.divergence.type if self.divergence else None,
            'buy_point_count': len(self.buy_points),
            'sell_point_count': len(self.sell_points),
            'latest_zhongshu': str(self.zhongshu_list[-1]) if self.zhongshu_list else None
        }
        
        return summary


def analyze_chanlun(df: pd.DataFrame, config: Dict = None) -> Dict:
    """
    缠论分析便捷函数
    
    Args:
        df: OHLCV数据
        config: 配置参数
    
    Returns:
        分析结果
    """
    analyzer = ChanlunAnalyzer(config)
    return analyzer.analyze(df)