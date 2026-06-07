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
    type: str = "normal"  # 中枢类型: normal/expanded/newborn
    
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
        处理K线包含关系（严格缠论标准）
        
        规则：
        - 上升趋势（向上处理）：取高高（高点取最高，低点取最高）
        - 下降趋势（向下处理）：取低低（低点取最低，高点取最低）
        - 方向由相邻非包含K线的高点比较确定
        - 方向未确定时遇到包含K线则跳过（保留prev作参考）
        - 高点相等时对比低点确定方向
        
        Args:
            klines: 原始K线列表
        
        Returns:
            处理后的无包含K线列表
        """
        if len(klines) < 2:
            return klines
        
        result = [klines[0]]
        direction = None  # 'up' or 'down'
        
        for i in range(1, len(klines)):
            current = klines[i]
            prev = result[-1]
            
            # 检查包含关系
            if KLineMerger.is_contained(prev, current):
                if direction is not None:
                    # 方向已知，合并：向上取高高，向下取低低
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
                    # 合并后不改变方向
                # 方向未知：跳过当前包含K线，用下一根非包含K线确定方向
            else:
                # 非包含：更新方向
                if direction is None:
                    if current.high > prev.high:
                        direction = 'up'
                    elif current.high < prev.high:
                        direction = 'down'
                    else:
                        # 高点相等，对比低点
                        direction = 'up' if current.low >= prev.low else 'down'
                result.append(current)
        
        return result


class FractalDetector:
    """分型识别器（含严格确认机制）"""
    
    def __init__(self, confirm_bars: int = 1):
        """
        Args:
            confirm_bars: 分型确认所需的后续K线数（默认1根）
                          顶分型：后续K线不再创新高即确认
                          底分型：后续K线不再创新低即确认
        """
        self.confirm_bars = confirm_bars
    
    def detect(self, klines: List[KLine]) -> List[Fractal]:
        """
        识别顶底分型（严格缠论标准 + 确认机制）
        
        步骤：
        1. 用3根K线判定分型（标准缠论定义）
        2. 分型确认：后续K线不再反向突破（顶不再创新高，底不再创新低）
        3. 过滤连续同向分型，只保留最极端的（最高顶/最低底）
        4. 相邻分型必须交替（顶-底-顶-底）
        
        Args:
            klines: 无包含K线列表
        
        Returns:
            过滤后的分型列表
        """
        raw_fractals = []
        
        for i in range(1, len(klines) - 1):
            prev = klines[i - 1]
            curr = klines[i]
            next_k = klines[i + 1]
            
            # 顶分型：中间高，且左右两侧高点均低于中间
            if (curr.high > prev.high and curr.high > next_k.high and
                curr.low > prev.low and curr.low > next_k.low):
                # 确认：后续 confirm_bars 根K线不再创新高
                confirmed = True
                for c in range(1, self.confirm_bars + 1):
                    ci = i + 1 + c
                    if ci < len(klines):
                        if klines[ci].high > curr.high:
                            confirmed = False
                            break
                if confirmed:
                    raw_fractals.append(Fractal(
                        type='top',
                        idx=curr.idx,
                        price=curr.high,
                        date=curr.date,
                        kline=curr
                    ))
            
            # 底分型：中间低，且左右两侧低点均高于中间
            if (curr.low < prev.low and curr.low < next_k.low and
                curr.high < prev.high and curr.high < next_k.high):
                # 确认：后续 confirm_bars 根K线不再创新低
                confirmed = True
                for c in range(1, self.confirm_bars + 1):
                    ci = i + 1 + c
                    if ci < len(klines):
                        if klines[ci].low < curr.low:
                            confirmed = False
                            break
                if confirmed:
                    raw_fractals.append(Fractal(
                        type='bottom',
                        idx=curr.idx,
                        price=curr.low,
                        date=curr.date,
                        kline=curr
                    ))
        
        # 过滤连续同向分型，只保留最极端的
        if not raw_fractals:
            return []
        
        filtered = [raw_fractals[0]]
        for f in raw_fractals[1:]:
            prev = filtered[-1]
            if f.type == prev.type:
                # 同向：保留更极端的
                if f.type == 'top' and f.price > prev.price:
                    filtered[-1] = f  # 保留更高的顶
                elif f.type == 'bottom' and f.price < prev.price:
                    filtered[-1] = f  # 保留更低的底
                # 否则跳过当前分型
            else:
                # 异向：直接追加（已保证交替性）
                filtered.append(f)
        
        return filtered


class StrokeBuilder:
    """笔构建器"""
    
    def __init__(self, min_klines: int = 4, min_amplitude_pct: float = 3.0):
        """
        Args:
            min_klines: 笔包含的最少K线数（顶底分型之间）
            min_amplitude_pct: 笔最低价格变动幅度百分比（默认3%）
                               低于此值认为是无效笔，跳过
        """
        self.min_klines = min_klines
        self.min_amplitude_pct = min_amplitude_pct
    
    def build(self, fractals: List[Fractal]) -> List[Stroke]:
        """
        从分型构建笔（严格缠论标准）
        
        规则：
        1. 笔必须方向交替（向上→向下→向上→...）
        2. 分型必须交替（底-顶或顶-底）
        3. 同向分型出现时保留更极端的作为新起点（回溯机制）
        4. 前后分型之间至少包含min_klines根K线
        5. 价格方向必须合理（向上笔顶>底，向下笔顶>底）
        
        Args:
            fractals: 过滤后的分型列表（已保证相邻异向）
        
        Returns:
            笔列表
        """
        strokes = []
        if len(fractals) < 2:
            return strokes
        
        i = 0
        while i < len(fractals):
            f1 = fractals[i]
            
            # 如果已有笔，检查方向交替
            if strokes:
                last_stroke = strokes[-1]
                # 上一笔是向上→下一笔起点应为顶分型
                # 上一笔是向下→下一笔起点应为底分型
                expected_type = 'top' if last_stroke.direction == 'up' else 'bottom'
                if f1.type != expected_type:
                    i += 1
                    continue
            
            # 寻找匹配的结束分型（取第一个有效配对）
            j = i + 1
            match_j = None
            
            while j < len(fractals):
                f2 = fractals[j]
                
                # 同向分型：保留更极端的作为新起点，重新开始搜索
                if f1.type == f2.type:
                    if f1.type == 'top' and f2.price > f1.price:
                        f1 = f2  # 更高的顶成为新起点
                        i = j
                    elif f1.type == 'bottom' and f2.price < f1.price:
                        f1 = f2  # 更低的底成为新起点
                        i = j
                    j += 1
                    match_j = None  # 新起点需重新匹配
                    continue
                
                # 检查间距（至少包含min_klines根独立K线）
                k_count = f2.idx - f1.idx
                if k_count < self.min_klines:
                    j += 1
                    continue
                
                # 检查价格方向合理性 + 最低幅度
                amp_pct = abs(f2.price - f1.price) / max(f1.price, 0.01) * 100
                if f1.type == 'bottom' and f2.type == 'top' and f2.price > f1.price:
                    if amp_pct >= self.min_amplitude_pct:
                        match_j = j
                        break  # 第一个有效向上笔
                elif f1.type == 'top' and f2.type == 'bottom' and f1.price > f2.price:
                    if amp_pct >= self.min_amplitude_pct:
                        match_j = j
                        break  # 第一个有效向下笔
                
                j += 1
            
            if match_j is None:
                break  # 找不到有效配对
            
            f2 = fractals[match_j]
            
            # 确定方向
            if f1.type == 'bottom':
                direction = 'up'
                high = f2.price
                low = f1.price
            else:
                direction = 'down'
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
            
            # 从match_j位置继续（f2的索引）
            i = match_j
        
        return strokes


class SegmentAnalyzer:
    """线段分析器 — 基于特征序列的线段终结逻辑"""
    
    def __init__(self, min_stroke_count: int = 3):
        self.min_stroke_count = min_stroke_count
    
    def build(self, strokes: List[Stroke]) -> List[Segment]:
        """
        从笔构建线段
        
        基于特征序列的线段生成逻辑：
        - 线段由至少 min_stroke_count 笔构成
        - 三笔之间存在重叠则形成线段
        - 线段延续：后续笔不破坏特征序列关系时，线段延续
        - 线段终结：特征序列被反向笔破坏
        
        特征序列定义：
          上升段：观察下跌笔（奇数笔）——若跌破前笔低点，段终结
          下降段：观察上涨笔（偶数笔）——若突破前笔高点，段终结
        """
        segments = []
        if len(strokes) < self.min_stroke_count:
            return segments
        
        i = 0
        while i <= len(strokes) - self.min_stroke_count:
            s1, s2, s3 = strokes[i], strokes[i+1], strokes[i+2]
            
            if not self._is_valid_segment(s1, s2, s3):
                i += 1
                continue
            
            seg_direction = s1.direction
            current_strokes = [s1, s2, s3]
            
            # 尝试延续线段（特征序列法）
            j = i + 3
            while j < len(strokes):
                next_stroke = strokes[j]
                
                # 特征序列终结判定
                if seg_direction == 'up':
                    # 上升段：下跌笔（反向笔）跌破前一笔低点 → 终结
                    if next_stroke.direction == 'down' and len(current_strokes) >= 2:
                        last_bull = current_strokes[-1]
                        ref_low = last_bull.low if last_bull.low is not None else last_bull.start_price
                        if next_stroke.end_price < ref_low:
                            break
                else:
                    # 下降段：上涨笔（反向笔）突破前一笔高点 → 终结
                    if next_stroke.direction == 'up' and len(current_strokes) >= 2:
                        last_bear = current_strokes[-1]
                        ref_high = last_bear.high if last_bear.high is not None else last_bear.start_price
                        if next_stroke.end_price > ref_high:
                            break
                
                current_strokes.append(next_stroke)
                j += 1
            
            segment = self._create_segment_from_strokes(current_strokes)
            segments.append(segment)
            i = j
        
        return segments
    
    def _create_segment_from_strokes(self, strokes: List[Stroke]) -> Segment:
        """从笔列表创建线段"""
        first = strokes[0]
        last = strokes[-1]
        direction = first.direction
        
        seg_high = max(
            max(s.end_price if s.direction == 'up' else s.start_price,
                s.high if s.high is not None else s.end_price)
            for s in strokes
        )
        seg_low = min(
            min(s.end_price if s.direction == 'down' else s.start_price,
                s.low if s.low is not None else s.start_price)
            for s in strokes
        )
        
        return Segment(
            start_idx=first.start_idx,
            end_idx=last.end_idx,
            start_price=first.start_price,
            end_price=last.end_price,
            start_date=first.start_date,
            end_date=last.end_date,
            direction=direction,
            strokes=strokes,
            high=seg_high,
            low=seg_low,
        )
    
    def _is_valid_segment(self, s1: Stroke, s2: Stroke, s3: Stroke) -> bool:
        """判断三笔是否构成线段"""
        if s1.direction == s2.direction or s2.direction == s3.direction:
            return False
        return self._has_overlap(s1, s2, s3)
    
    def _has_overlap(self, s1: Stroke, s2: Stroke, s3: Stroke) -> bool:
        """检查三笔是否有重叠"""
        if s1.direction == 'up':
            overlap_low = max(s1.start_price, s2.low if s2.low is not None else s2.start_price)
            overlap_high = min(s3.end_price, s2.high if s2.high is not None else s2.end_price)
            return overlap_low <= overlap_high
        else:
            overlap_low = max(s2.low if s2.low is not None else s2.start_price,
                            s3.start_price)
            overlap_high = min(s1.start_price, s2.high if s2.high is not None else s2.end_price)
            return overlap_low <= overlap_high

class ZhongshuAnalyzer:
    """中枢分析器 — 支持延伸/新生/扩张 + 最小宽度过滤"""
    
    def __init__(self, min_segment_count: int = 3, min_width: float = 1.0):
        self.min_segment_count = min_segment_count
        self.min_width = min_width
    
    def find(self, segments: List[Segment]) -> List[Zhongshu]:
        """
        识别中枢并处理演化
        
        中枢定义：由至少3段构成，三段存在重叠区域
        
        支持演化：
          - 延伸：后续线段进入中枢区间 → 合并到当前中枢
          - 新生：离开中枢后新线段构成新中枢
          - 扩张：两个有重叠的中枢合并为一个
          - 过滤：宽度 < min_width 的中枢被丢弃
        """
        zhongshu_list = []
        
        i = 0
        while i <= len(segments) - self.min_segment_count:
            seg1 = segments[i]
            seg2 = segments[i + 1]
            seg3 = segments[i + 2]
            
            overlap = self._calculate_overlap(seg1, seg2, seg3)
            if overlap is None:
                i += 1
                continue
            
            low, high = overlap
            if high - low < self.min_width:
                i += 1
                continue
            
            # 创建初始中枢
            zs = self._create_zhongshu(seg1, seg2, seg3, overlap)
            zs.type = 'normal'
            zs_end_idx = i + 3
            
            # 尝试延伸：后续线段是否进入中枢
            j = i + 3
            while j < len(segments):
                seg = segments[j]
                seg_r = seg.range
                
                if seg_r['low'] <= zs.high and seg_r['high'] >= zs.low:
                    # 重叠 → 延伸中枢
                    low_new = min(zs.low, seg_r['low'])
                    high_new = max(zs.high, seg_r['high'])
                    zs.low = low_new
                    zs.high = high_new
                    zs.center = (low_new + high_new) / 2
                    zs.range_width = high_new - low_new
                    zs.end_idx = seg.end_idx
                    zs.end_date = seg.end_date
                    if zs.segments is not None:
                        zs.segments = zs.segments + [seg]
                    zs_end_idx = j + 1
                    j += 1
                else:
                    # 不重叠 → 延伸结束，检测新生/扩张
                    remaining = len(segments) - j
                    if remaining >= 2:
                        seg_b = segments[j + 1]
                        seg_c = segments[j + 2]
                        new_ov = self._calculate_overlap(seg, seg_b, seg_c)
                        if new_ov is not None:
                            n_low, n_high = new_ov
                            if n_high - n_low >= self.min_width:
                                # 检查是否与前中枢有重叠 → 扩张
                                if seg_r['low'] < zs.high and seg_r['high'] > zs.low:
                                    zs.type = 'expanded'
                                    zs.low = min(zs.low, n_low)
                                    zs.high = max(zs.high, n_high)
                                    zs_end_idx = j + 3
                                else:
                                    # 新生中枢
                                    new_zs = self._create_zhongshu(seg, seg_b, seg_c, new_ov)
                                    new_zs.type = 'newborn'
                                    zhongshu_list.append(new_zs)
                    break
            
            zhongshu_list.append(zs)
            i = zs_end_idx
        
        return zhongshu_list
    
    def _calculate_overlap(self, seg1: Segment, seg2: Segment, seg3: Segment) -> Optional[tuple]:
        """计算三段的重叠区间"""
        ranges = [seg1.range, seg2.range, seg3.range]
        overlap_low = max(r['low'] for r in ranges)
        overlap_high = min(r['high'] for r in ranges)
        return (overlap_low, overlap_high) if overlap_low <= overlap_high else None
    
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
        识别第二类买卖点（仅找第一个符合条件的回调/反弹）
        
        第二类买点：第一类买点后上涨，回调不创新低
        第二类卖点：第一类卖点后下跌，反弹不创新高

        只识别一次：第一类买卖点之后的第一个有效回调/反弹配对。
        避免历史循环中多次生成第二类买卖点。
        """
        second_buy = []
        second_sell = []
        
        if existing_buy:
            first_buy = existing_buy[0]
            first_buy_idx = first_buy.position.get('idx', 0)
            first_buy_price = first_buy.position.get('price', 0)
            
            # 只找第一类买点后的第一个有效配对
            for i, stroke in enumerate(strokes):
                if stroke.start_idx <= first_buy_idx:
                    continue
                if stroke.direction == 'up' and i < len(strokes) - 1:
                    next_stroke = strokes[i + 1]
                    if next_stroke.direction == 'down' and next_stroke.end_price > first_buy_price:
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
                        break  # 只识别一次
        
        if existing_sell:
            first_sell = existing_sell[0]
            first_sell_idx = first_sell.position.get('idx', 0)
            first_sell_price = first_sell.position.get('price', 0)
            
            # 只找第一类卖点后的第一个有效配对
            for i, stroke in enumerate(strokes):
                if stroke.start_idx <= first_sell_idx:
                    continue
                if stroke.direction == 'down' and i < len(strokes) - 1:
                    next_stroke = strokes[i + 1]
                    if next_stroke.direction == 'up' and next_stroke.end_price < first_sell_price:
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
                        break  # 只识别一次
        
        return {'buy': second_buy, 'sell': second_sell}
    
    def _find_third_points(self, strokes: List[Stroke],
                          zhongshu_list: List[Zhongshu]) -> Dict[str, List]:
        """
        识别第三类买卖点（聚焦最新中枢形成之后）
        
        第三类买点：上涨回调不进入中枢
        第三类卖点：下跌反弹不进入中枢
        
        只搜索最新中枢 end_idx 之后的笔，避免全局历史堆积。
        """
        third_buy = []
        third_sell = []
        
        if not zhongshu_list:
            return {'buy': third_buy, 'sell': third_sell}
        
        latest_zhongshu = zhongshu_list[-1]
        # 只搜索最新中枢形成之后的笔
        min_idx = latest_zhongshu.end_idx
        
        for i, stroke in enumerate(strokes[:-1]):
            # 跳过中枢形成之前的笔
            if stroke.start_idx < min_idx:
                continue
            
            # 第三类买点：上涨后回调
            if stroke.direction == 'up':
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
            elif stroke.direction == 'down':
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
            min_klines=self.config.get('min_klines', 4)
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
            'min_klines': 4,  # 笔包含的最少K线数
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
        """数据预处理
        
        从 DataFrame 提取 KLine 列表：
        - idx 始终为顺序整数（自 0 递增），保证减法运算得到 int
        - date 优先取自 trade_date 列，回退到 DataFrame index（统一转为 str）
        """
        self.klines = []
        
        # 准备 date 序列
        if 'trade_date' in df.columns:
            date_values = df['trade_date'].astype(str).tolist()
        else:
            date_values = df.index.astype(str).tolist()
        
        for enum_idx, (_, row) in enumerate(df.iterrows()):
            kl = KLine(
                idx=enum_idx,
                open=row['open'],
                high=row['high'],
                low=row['low'],
                close=row['close'],
                date=date_values[enum_idx],
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

# ==========================================
# 以下是新增的核心模块
# ==========================================
from abc import ABC, abstractmethod
from typing import Dict, List, Optional, Any, Tuple
from datetime import datetime
import pandas as pd
import numpy as np
from dataclasses import dataclass


import logging
logger = logging.getLogger(__name__)
# 导入框架基类
try:
    from . import AlphaModel, Insight, UniverseSelectionModel
except ImportError:
    # 定义本地基类以确保独立运行
    class Insight:
        LONG = 1
        SHORT = -1
        FLAT = 0
        def __init__(self, symbol: str, direction: int, confidence: float, weight: float, reason: str = ""):
            self.symbol = symbol
            self.direction = direction
            self.confidence = confidence
            self.weight = weight
            self.reason = reason
            self.created_at = datetime.now()
    
    class AlphaModel(ABC):
        @abstractmethod
        def generate_insights(self, data: Any) -> List[Insight]:
            pass
    
    class UniverseSelectionModel(ABC):
        @abstractmethod
        def select(self, date_time: datetime, data: Any) -> List[str]:
            pass

class ChanlunScorer:
    """缠论评分系统"""
    
    @staticmethod
    def score(analysis_result: Dict, latest_close: float = None) -> Dict:
        """
        根据缠论分析结果评分
        
        Args:
            analysis_result: ChanlunAnalyzer的分析结果
            latest_close: 最新收盘价（可选），用于价格匹配度评估
        
        Returns:
            评分结果
        """
        score = 0
        details = []
        
        buy_points = analysis_result.get('buy_points', [])
        sell_points = analysis_result.get('sell_points', [])
        
        # 买卖点评分
        if buy_points:
            score += 30
            details.append(f"发现{len(buy_points)}个买点")
            for bp in buy_points:
                if bp.type == 'first_buy':
                    score += 20
                    details.append(f"第一类买点(+20), 置信度: {bp.confidence:.2f}")
                elif bp.type == 'second_buy':
                    score += 15
                    details.append(f"第二类买点(+15), 置信度: {bp.confidence:.2f}")
                elif bp.type == 'third_buy':
                    score += 10
                    details.append(f"第三类买点(+10), 置信度: {bp.confidence:.2f}")
        
        if sell_points:
            score -= 20
            details.append(f"发现{len(sell_points)}个卖点")
            for sp in sell_points:
                if sp.type == 'first_sell':
                    score -= 15
                    details.append(f"第一类卖点(-15), 置信度: {sp.confidence:.2f}")
                elif sp.type == 'second_sell':
                    score -= 10
                    details.append(f"第二类卖点(-10), 置信度: {sp.confidence:.2f}")
                elif sp.type == 'third_sell':
                    score -= 8
                    details.append(f"第三类卖点(-8), 置信度: {sp.confidence:.2f}")
        
        # 价格匹配度调整（防止高分但已远离买点）
        if latest_close is not None:
            if buy_points:
                # 检查所有买点与当前价的偏差，取最严重的惩罚
                worst_penalty = 0
                for bp in buy_points:
                    buy_price = bp.position.get('price', 0) if bp.position else 0
                    if buy_price > 0:
                        pct = (latest_close / buy_price - 1) * 100
                        if pct < -5:
                            p = min(30, int(abs(pct) * 2))
                            if p > worst_penalty:
                                worst_penalty = p
                                details.append(f"买点{buy_price:.2f}已跌破{pct:.0f}%(-{p}), 信号衰减")
                        elif pct > 30:
                            p = min(15, int(pct * 0.3))
                            if p > worst_penalty:
                                worst_penalty = p
                                details.append(f"距离买点{buy_price:.2f}已涨{pct:.0f}%( -{p}), 追高风险")
                score -= worst_penalty
            
            if sell_points:
                # 检查所有卖点，取最大加分
                total_bonus = 0
                for sp in sell_points:
                    sell_price = sp.position.get('price', 0) if sp.position else 0
                    if sell_price > 0:
                        pct = (latest_close / sell_price - 1) * 100
                        if pct > 5:
                            bonus = min(20, int(pct * 1.5))
                            total_bonus += bonus
                            details.append(f"价格反弹超卖点{sell_price:.2f}({pct:.0f}%, +{bonus}), 卖点信号衰减")
                score += min(total_bonus, 20)
        
        divergence = analysis_result.get('divergence')
        if divergence:
            if divergence.direction == 'up':
                score += 15
                details.append(f"底背驰(+15), 类型: {divergence.type}")
            else:
                score -= 10
                details.append(f"顶背驰(-10), 类型: {divergence.type}")
        
        trend = analysis_result.get('trend', 'unknown')
        if trend == 'up':
            score += 10
            details.append(f"上升趋势(+10)")
        elif trend == 'down':
            score -= 5
            details.append(f"下降趋势(-5)")
        
        zhongshu_list = analysis_result.get('zhongshu', [])
        if zhongshu_list:
            score += 5
            details.append(f"中枢形成(+5), 数量: {len(zhongshu_list)}")
        
        # ── 多中枢矛盾检测 ──
        if len(zhongshu_list) >= 2:
            # 检查多个中枢的方向是否一致
            directions = set()
            for zs in zhongshu_list:
                if hasattr(zs, 'direction') and zs.direction:
                    directions.add(zs.direction)
            if len(directions) > 1:
                score -= 10
                details.append(f"多中枢方向矛盾({directions})(-10), 信号冲突")
        
        # ── 笔段矛盾检测 ──
        strokes = analysis_result.get('strokes', [])
        segments = analysis_result.get('segments', [])
        if strokes and segments and len(strokes) >= 2 and len(segments) >= 1:
            last_stroke = strokes[-1]
            last_segment = segments[-1]
            if last_stroke.direction != last_segment.direction:
                score -= 8
                details.append(f"笔段方向矛盾(笔:{last_stroke.direction} vs 段:{last_segment.direction})(-8)")
        
        # ── 中枢类型标记解读 ──
        for zs in zhongshu_list:
            if hasattr(zs, 'type') and zs.type in ('expanded',):
                score -= 5
                details.append(f"中枢扩张(-5): 顶底区间扩大，趋势不稳定")

        
        score = max(0, min(100, score + 50))
        
        return {
            'score': score,
            'details': details,
            'recommendation': ChanlunScorer._get_recommendation(score)
        }
    
    @staticmethod
    def _get_recommendation(score: float) -> str:
        """根据分数获取建议"""
        if score >= 70:
            return 'STRONG_BUY'
        elif score >= 55:
            return 'BUY'
        elif score >= 45:
            return 'HOLD'
        elif score >= 30:
            return 'SELL'
        else:
            return 'STRONG_SELL'

class ChanlunAlphaModel(AlphaModel):
    """缠论Alpha模型 - 第三层策略验证"""
    
    def __init__(self, config: Dict = None):
        """
        Args:
            config: 配置参数
        """
        self.config = config or {}
        self.analyzer = ChanlunAnalyzer(self.config)
        self.scorer = ChanlunScorer()
    
    def generate_insights(self, data: Dict[str, pd.DataFrame]) -> List[Insight]:
        """
        对筛选后的股票进行缠论分析并生成Insight信号
        
        Args:
            data: 股票数据字典 {symbol: DataFrame}
        
        Returns:
            Insight信号列表
        """
        insights = []
        
        for symbol, df in data.items():
            try:
                if len(df) < 60:
                    continue
                
                analysis_result = self.analyzer.analyze(df)
                
                if 'error' in analysis_result:
                    continue
                
                score_result = self.scorer.score(analysis_result)
                score = score_result['score']
                
                if score >= 60:
                    direction = Insight.LONG
                    confidence = min(1.0, score / 100)
                    reason = f"缠论评分: {score:.1f}, " + "; ".join(score_result['details'][:3])
                elif score <= 40:
                    direction = Insight.SHORT
                    confidence = min(1.0, (100 - score) / 100)
                    reason = f"缠论评分: {score:.1f}, " + "; ".join(score_result['details'][:3])
                else:
                    continue
                
                insights.append(Insight(
                    symbol=symbol,
                    direction=direction,
                    confidence=confidence,
                    weight=0.3,
                    reason=reason
                ))
                
            except Exception as e:
                logger.error(f"缠论分析{symbol}失败: {e}")
        
        return insights

class SignalFusion:
    """信号融合器"""
    
    def __init__(self, weights: Dict[str, float] = None):
        """
        Args:
            weights: 各策略权重
        """
        self.weights = weights or {
            'chanlun': 0.3,
            'chip': 0.4,
            'factor': 0.3
        }
    
    def fuse(self, signals_dict: Dict[str, List[Insight]]) -> Dict:
        """
        融合多策略信号
        
        Args:
            signals_dict: 各策略信号 {strategy_name: [Insight]}
        
        Returns:
            融合结果
        """
        symbol_signals = {}
        
        for strategy_name, signals in signals_dict.items():
            for signal in signals:
                symbol = signal.symbol
                if symbol not in symbol_signals:
                    symbol_signals[symbol] = {
                        'signals': {},
                        'total_weight': 0
                    }
                
                strategy_weight = self.weights.get(strategy_name, 0.33)
                signal_value = signal.direction * signal.confidence
                
                symbol_signals[symbol]['signals'][strategy_name] = {
                    'direction': signal.direction,
                    'confidence': signal.confidence,
                    'weight': strategy_weight,
                    'value': signal_value,
                    'reason': signal.reason
                }
                
                symbol_signals[symbol]['total_weight'] += strategy_weight
        
        results = []
        for symbol, data in symbol_signals.items():
            fused_value = 0
            total_weight = 0
            
            for strategy_name, signal in data['signals'].items():
                weight = signal['weight']
                value = signal['value']
                fused_value += value * weight
                total_weight += weight
            
            if total_weight > 0:
                fused_value = fused_value / total_weight
            
            if fused_value > 0.3:
                action = 'BUY'
                direction = Insight.LONG
            elif fused_value < -0.3:
                action = 'SELL'
                direction = Insight.SHORT
            else:
                action = 'HOLD'
                direction = Insight.FLAT
            
            results.append({
                'symbol': symbol,
                'action': action,
                'direction': direction,
                'fused_value': fused_value,
                'confidence': abs(fused_value),
                'signals': data['signals']
            })
        
        return {
            'action_count': {
                'BUY': len([r for r in results if r['action'] == 'BUY']),
                'SELL': len([r for r in results if r['action'] == 'SELL']),
                'HOLD': len([r for r in results if r['action'] == 'HOLD'])
            },
            'results': results
        }

class StrategyValidationLayer:
    """第三层：策略验证层"""
    
    def __init__(self):
        self.alpha_models = {
            'chanlun': ChanlunAlphaModel()
        }
        self.signal_fusion = SignalFusion()
    
    def validate(self, candidates: List[Dict], stock_data: Dict[str, pd.DataFrame]) -> List[Dict]:
        """
        对候选股票进行多策略验证
        
        Args:
            candidates: 第二层筛选出的股票列表
            stock_data: 完整股票数据
        
        Returns:
            通过验证的股票列表
        """
        candidate_symbols = []
        for c in candidates:
            symbol = c.get('symbol') or c.get('code')
            if symbol:
                candidate_symbols.append(symbol)
        
        relevant_data = {}
        for s in candidate_symbols:
            if s in stock_data:
                relevant_data[s] = stock_data[s]
        
        all_signals = {}
        for model_name, model in self.alpha_models.items():
            try:
                signals = model.generate_insights(relevant_data)
                all_signals[model_name] = signals
            except Exception as e:
                logger.error(f"策略{model_name}执行失败: {e}")
        
        fusion_result = self.signal_fusion.fuse(all_signals)
        
        validated = []
        for result in fusion_result['results']:
            if result['action'] in ['BUY']:
                original_candidate = None
                for c in candidates:
                    if (c.get('symbol') == result['symbol']) or (c.get('code') == result['symbol']):
                        original_candidate = c
                        break
                
                if original_candidate:
                    validated.append({
                        **original_candidate,
                        'signals': result['signals'],
                        'fused_value': result['fused_value'],
                        'confidence': result['confidence'],
                        'final_action': result['action']
                    })
        
        return validated

from .screener import DarwinRiskFilter as _RealDarwinRiskFilter

class DarwinRiskFilter(_RealDarwinRiskFilter):
    """
    达尔文风险过滤 - 委托给 screener.DarwinRiskFilter（方案G）
    
    保持 UniverseSelectionModel 接口兼容，实际逻辑由父类实现。
    """
    pass


class MultiLayerStockScreener:
    """完整的三层筛选器"""
    
    def __init__(self):
        self.risk_filter = DarwinRiskFilter()
        self.validation_layer = StrategyValidationLayer()
    
    def screen(self, all_stocks: List[str], stock_data: Dict[str, pd.DataFrame]) -> List[Dict]:
        """
        完整的三层筛选流程
        
        Args:
            all_stocks: 全市场股票
            stock_data: 股票数据
        
        Returns:
            最终精选股票列表
        """
        risk_passed = self.risk_filter.filter(all_stocks, stock_data)
        
        chip_candidates = self._chip_selection(risk_passed, stock_data)
        
        final_candidates = self.validation_layer.validate(chip_candidates, stock_data)
        
        return final_candidates
    
    def _chip_selection(self, symbols: List[str], stock_data: Dict[str, pd.DataFrame]) -> List[Dict]:
        """第二层：筹码筛选（简化实现）"""
        candidates = []
        
        for symbol in symbols:
            df = stock_data.get(symbol)
            if df is None or len(df) < 60:
                continue
            
            candidates.append({
                'symbol': symbol,
                'code': symbol,
                'chip_score': 60,
                'phase': 'unknown'
            })
        
        return candidates

def analyze_single_stock(symbol: str, data: pd.DataFrame) -> Dict:
    """
    单只股票完整分析（用户自选股支持）
    
    Args:
        symbol: 股票代码
        data: K线数据
    
    Returns:
        完整分析报告
    """
    analysis_result = {'symbol': symbol}
    
    risk_filter = DarwinRiskFilter()
    risk_check = risk_filter._apply_filters(symbol, data)
    analysis_result['risk_check'] = {'passed': risk_check, 'reasons': []}

    
    try:
        analyzer = ChanlunAnalyzer()
        chanlun_result = analyzer.analyze(data)
        
        if 'error' in chanlun_result:
            analysis_result['chanlun'] = {'error': chanlun_result['error']}
        else:
            scorer = ChanlunScorer()
            score_result = scorer.score(chanlun_result)
            
            analysis_result['chanlun'] = {
                'success': True,
                'summary': chanlun_result.get('summary', {}),
                'score': score_result['score'],
                'recommendation': score_result['recommendation'],
                'buy_points': len(chanlun_result.get('buy_points', [])),
                'sell_points': len(chanlun_result.get('sell_points', [])),
                'trend': chanlun_result.get('trend', 'unknown'),
                'has_zhongshu': len(chanlun_result.get('zhongshu', [])) > 0,
                'has_divergence': chanlun_result.get('divergence') is not None
            }
    except Exception as e:
        analysis_result['chanlun'] = {'error': str(e)}
    
    return analysis_result