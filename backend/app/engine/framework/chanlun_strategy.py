"""
缠论策略模块
实现完整的缠论分析功能，包括线段识别、中枢识别、背驰判断和买卖点识别
参考 CZSC 项目和缠论量化策略指南设计
"""
from typing import Dict, List, Optional, Any, Tuple
from datetime import datetime
import pandas as pd
import numpy as np
from dataclasses import dataclass


def calc_macd(closes: np.ndarray) -> Tuple[np.ndarray, np.ndarray, np.ndarray]:
    """计算MACD: 返回 (dif, dea, macd_hist)"""
    if len(closes) < 26:
        return np.zeros(len(closes)), np.zeros(len(closes)), np.zeros(len(closes))
    s = pd.Series(closes)
    ema12 = s.ewm(span=12).mean().values
    ema26 = s.ewm(span=26).mean().values
    dif = ema12 - ema26
    dea = pd.Series(dif).ewm(span=9).mean().values
    macd_hist = 2 * (dif - dea)
    return dif, dea, macd_hist


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

    def get_last_unconfirmed_fractal(self, klines: List[KLine], last_confirmed_idx: int) -> Dict:
        """
        检测未确认的潜在分型（已形成3K结构但尚未满足确认条件）

        Args:
            klines: 无包含K线列表
            last_confirmed_idx: 最后一个已确认分型的 idx（从该位置 +1 开始扫描）

        Returns:
            {
                'has_unconfirmed': bool,   # 是否存在未确认分型
                'direction': str,          # 'PENDING_UP' / 'PENDING_DOWN' / 'NONE'
                'potential_type': str,     # 'top' / 'bottom' / 'none'
                'start_idx': int,          # 潜在分型的中间K线 idx
                'price': float             # 顶分型取 high，底分型取 low
            }
        """
        result: Dict = {
            'has_unconfirmed': False,
            'direction': 'NONE',
            'potential_type': 'none',
            'start_idx': -1,
            'price': 0.0
        }

        if len(klines) < 3:
            return result

        start = max(last_confirmed_idx + 1, 1)
        for i in range(start, len(klines) - 1):
            prev = klines[i - 1]
            curr = klines[i]
            next_k = klines[i + 1]

            # 顶分型判定：中间 high > 左右 high，中间 low > 左右 low
            if (curr.high > prev.high and curr.high > next_k.high and
                curr.low > prev.low and curr.low > next_k.low):
                result = {
                    'has_unconfirmed': True,
                    'direction': 'PENDING_DOWN',  # 顶分型预示向下
                    'potential_type': 'top',
                    'start_idx': curr.idx,
                    'price': curr.high
                }
                break

            # 底分型判定：中间 low < 左右 low，中间 high < 左右 high
            if (curr.low < prev.low and curr.low < next_k.low and
                curr.high < prev.high and curr.high < next_k.high):
                result = {
                    'has_unconfirmed': True,
                    'direction': 'PENDING_UP',  # 底分型预示向上
                    'potential_type': 'bottom',
                    'start_idx': curr.idx,
                    'price': curr.low
                }
                break

        return result


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

    def _has_feature_sequence_gap(self, next_stroke: Stroke, ref_stroke: Stroke, seg_direction: str) -> bool:
        """
        检查特征序列元素之间是否存在跳空缺口

        上升段的反向笔（下跌笔）为特征序列：
          - 若 next_stroke.end_price > ref_stroke.start_price → 向上跳空缺口
          - 特征元素未实际触及参考点，不视为终结

        下降段的反向笔（上涨笔）为特征序列：
          - 若 next_stroke.end_price < ref_stroke.start_price → 向下跳空缺口
          - 特征元素未实际触及参考点，不视为终结
        """
        if seg_direction == 'up':
            # 上升段：下跌笔作为特征序列元素
            # 若当前下跌笔的 end_price 高于前一笔的 start_price → 向上跳空缺口
            return next_stroke.direction == 'down' and next_stroke.end_price > ref_stroke.start_price
        else:
            # 下降段：上涨笔作为特征序列元素
            # 若当前上涨笔的 end_price 低于前一笔的 start_price → 向下跳空缺口
            return next_stroke.direction == 'up' and next_stroke.end_price < ref_stroke.start_price

    def _is_feature_sequence_break_down(self, feature_strokes: List[Stroke], threshold: int = 3) -> bool:
        """
        检查上升段的特征序列（下跌笔）是否形成顶分型破坏

        若连续 threshold 笔下跌笔的 end_price 依次降低（每笔低于前笔），
        则特征序列被破坏 = 线段终结
        """
        down_strokes = [s for s in feature_strokes if s.direction == 'down']
        if len(down_strokes) < threshold:
            return False

        # 检查最近 threshold 笔是否 end_price 依次降低
        recent = down_strokes[-threshold:]
        for k in range(1, len(recent)):
            if not (recent[k].end_price < recent[k-1].end_price):
                return False
        return True

    def _is_feature_sequence_break_up(self, feature_strokes: List[Stroke], threshold: int = 3) -> bool:
        """
        检查下降段的特征序列（上涨笔）是否形成底分型破坏

        若连续 threshold 笔上涨笔的 end_price 依次升高（每笔高于前笔），
        则特征序列被破坏 = 线段终结
        """
        up_strokes = [s for s in feature_strokes if s.direction == 'up']
        if len(up_strokes) < threshold:
            return False

        # 检查最近 threshold 笔是否 end_price 依次升高
        recent = up_strokes[-threshold:]
        for k in range(1, len(recent)):
            if not (recent[k].end_price > recent[k-1].end_price):
                return False
        return True

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
                        # [P1-#8] 特征序列缺口处理：检查是否有跳空缺口
                        if self._has_feature_sequence_gap(next_stroke, current_strokes[-1], seg_direction):
                            current_strokes.append(next_stroke)
                            j += 1
                            continue
                else:
                    # 下降段：上涨笔（反向笔）突破前一笔高点 → 终结
                    if next_stroke.direction == 'up' and len(current_strokes) >= 2:
                        last_bear = current_strokes[-1]
                        ref_high = last_bear.high if last_bear.high is not None else last_bear.start_price
                        if next_stroke.end_price > ref_high:
                            break
                        # [P1-#8] 特征序列缺口处理：检查是否有跳空缺口
                        if self._has_feature_sequence_gap(next_stroke, current_strokes[-1], seg_direction):
                            current_strokes.append(next_stroke)
                            j += 1
                            continue
                
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
    
    def __init__(self, lookback_period: int = 120):
        """
        Args:
            lookback_period: 回看周期
        """
        self.lookback_period = lookback_period
        self._closes = None  # 外部传入的 close 数组（用于 MACD 计算）

    def detect(self, strokes: List[Stroke],
              zhongshu_list: List[Zhongshu] = None,
              volume: pd.Series = None,
              closes: np.ndarray = None) -> Optional[Divergence]:
        """
        检测背驰（支持 MACD 面积背驰确认）

        Args:
            strokes: 笔列表
            zhongshu_list: 中枢列表
            volume: 成交量数据
            closes: 收盘价数组，用于 MACD 面积计算

        Returns:
            背驰信息或None
        """
        if len(strokes) < 4:
            return None

        zhongshu_list = zhongshu_list or []
        self._closes = closes
        
        # 检测趋势背驰
        trend_div = self._detect_trend_divergence(strokes)

        # [P1-#19] 标准a+A+b+B+c趋势背驰检测
        trend_bt = self._detect_trend_backtesting(strokes, zhongshu_list, self._closes)
        if trend_div:
            if trend_bt:
                trend_div.details['trend_backtesting'] = trend_bt
            return trend_div

        if trend_bt:
            return Divergence(
                type='trend',
                direction=trend_bt['direction'],
                confidence=trend_bt['confidence'],
                details={'trend_backtesting': trend_bt}
            )
        
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
    
    def _calc_stroke_macd_area(self, stroke) -> float:
        """计算单根笔范围内的 MACD 柱面积（红绿柱代数累加）"""
        if self._closes is None or stroke.start_idx >= len(self._closes) or stroke.end_idx >= len(self._closes):
            return 0.0
        _, _, macd_hist = calc_macd(self._closes)
        # 笔区间内的 MACD 柱面积（代数累加，红柱正绿柱负）
        seg = macd_hist[stroke.start_idx:stroke.end_idx + 1]
        return float(np.sum(seg))

    def _detect_trend_divergence(self, strokes: List[Stroke]) -> Optional[Divergence]:
        """
        检测趋势背驰（MACD 面积确认版）

        原理：创新高/低后，力度明显减弱。
        双重确认：①笔幅度减弱（<80%）②MACD柱面积比减弱（<85%）
        """
        if len(strokes) < 4:
            return None

        # 获取最近的笔（方向交替）
        recent_up = [s for s in strokes if s.direction == 'up']
        recent_down = [s for s in strokes if s.direction == 'down']

        if len(recent_up) < 2 or len(recent_down) < 2:
            return None

        # ── 上涨趋势背驰 ──
        last_up = recent_up[-1]
        prev_up = recent_up[-2]

        if last_up.end_price > prev_up.end_price:
            current_amp = last_up.amplitude
            prev_amp = prev_up.amplitude

            if current_amp < prev_amp * 0.8:
                # 幅度确认 → 进一步检查 MACD 面积
                area_last = self._calc_stroke_macd_area(last_up)
                area_prev = self._calc_stroke_macd_area(prev_up)

                if area_prev == 0:
                    # 无 MACD 数据，纯幅度背驰
                    macd_confirmed = False
                    area_ratio = 0.0
                else:
                    area_ratio = abs(area_last / area_prev) if area_prev != 0 else 0.0
                    macd_confirmed = area_ratio < 0.85

                # 动态置信度
                if macd_confirmed:
                    # MACD 面积也确认 → 高置信度背驰
                    if area_ratio < 0.4:
                        adj_conf = 0.95  # 极强
                    elif area_ratio < 0.6:
                        adj_conf = 0.90  # 强
                    else:
                        adj_conf = 0.85  # 中等
                else:
                    adj_conf = 0.8  # 仅幅度，无 MACD 确认

                return Divergence(
                    type='trend',
                    direction='up',
                    confidence=adj_conf,
                    position={'idx': last_up.end_idx, 'price': last_up.end_price},
                    details={
                        'current_amplitude': current_amp,
                        'prev_amplitude': prev_amp,
                        'strength_ratio': current_amp / prev_amp,
                        'macd_area_ratio': round(area_ratio, 4),
                        'macd_confirmed': macd_confirmed,
                    }
                )

        # ── 下跌趋势背驰 ──
        last_down = recent_down[-1]
        prev_down = recent_down[-2]

        if last_down.end_price < prev_down.end_price:
            current_amp = last_down.amplitude
            prev_amp = prev_down.amplitude

            if current_amp < prev_amp * 0.8:
                # 幅度确认 → 进一步检查 MACD 面积
                area_last = self._calc_stroke_macd_area(last_down)
                area_prev = self._calc_stroke_macd_area(prev_down)

                if area_prev == 0:
                    macd_confirmed = False
                    area_ratio = 0.0
                else:
                    area_ratio = abs(area_last / area_prev) if area_prev != 0 else 0.0
                    macd_confirmed = area_ratio < 0.85

                if macd_confirmed:
                    if area_ratio < 0.4:
                        adj_conf = 0.95
                    elif area_ratio < 0.6:
                        adj_conf = 0.90
                    else:
                        adj_conf = 0.85
                else:
                    adj_conf = 0.8

                return Divergence(
                    type='trend',
                    direction='down',
                    confidence=adj_conf,
                    position={'idx': last_down.end_idx, 'price': last_down.end_price},
                    details={
                        'current_amplitude': current_amp,
                        'prev_amplitude': prev_amp,
                        'strength_ratio': current_amp / prev_amp,
                        'macd_area_ratio': round(area_ratio, 4),
                        'macd_confirmed': macd_confirmed,
                    }
                )

        return None

    def _detect_trend_backtesting(self, strokes: List, zhongshu_list: List, closes: np.ndarray) -> Optional[Dict]:
        """
        [P1-#19] 标准a+A+b+B+c趋势背驰检测

        识别两中枢+两段趋势的标准趋势背驰模型：
        比较c段与a段的MACD面积。

        Returns: None or {
            'type': 'trend_backtesting',
            'direction': 'up'|'down',
            'confidence': float,
            'a_stroke': Dict,
            'zs_a': Dict,
            'b_stroke': Dict,
            'zs_b': Dict,
            'c_stroke': Dict,
            'macd_area_ratio': float,
            'reason': str,
        }
        """
        if not zhongshu_list or len(zhongshu_list) < 2:
            return None
        if closes is None or len(closes) < 60:
            return None

        # 取最后两个中枢
        zs_a = zhongshu_list[-2]
        zs_b = zhongshu_list[-1]

        # a段：进入中枢A的笔（end_idx <= zs_a.start_idx）
        # b段：连接中枢A和中枢B的笔（start_idx >= zs_a.end_idx, end_idx <= zs_b.start_idx）
        # c段：离开中枢B的笔（start_idx >= zs_b.end_idx）
        a_stroke = None
        b_stroke = None
        c_stroke = None

        for s in strokes:
            if s.end_idx <= zs_a.start_idx:
                a_stroke = s
            elif s.start_idx >= zs_a.end_idx and s.end_idx <= zs_b.start_idx:
                b_stroke = s
            elif s.start_idx >= zs_b.end_idx:
                c_stroke = s

        if not all([a_stroke, b_stroke, c_stroke]):
            return None

        # 检查方向一致性
        direction = zs_a.direction
        if not direction:
            return None

        # MACD面积计算
        _, _, macd_hist = calc_macd(closes)

        def _stroke_macd_area(stroke, macd_hist):
            start = max(0, stroke.start_idx)
            end = min(len(macd_hist), stroke.end_idx + 1)
            return float(np.sum(macd_hist[start:end])) if end > start else 0

        area_a = _stroke_macd_area(a_stroke, macd_hist)
        area_c = _stroke_macd_area(c_stroke, macd_hist)

        if abs(area_a) < 0.001:
            return None

        area_ratio = abs(area_c / area_a) if area_a != 0 else 1.0

        # 置信度判定
        if area_ratio < 0.4:
            confidence = 0.95
            reason = f"c段/a段面积比={area_ratio:.2f}, 极强趋势背驰"
        elif area_ratio < 0.6:
            confidence = 0.85
            reason = f"c段/a段面积比={area_ratio:.2f}, 强烈趋势背驰"
        elif area_ratio < 0.85:
            confidence = 0.75
            reason = f"c段/a段面积比={area_ratio:.2f}, 标准趋势背驰"
        else:
            return None

        return {
            'type': 'trend_backtesting',
            'direction': direction,
            'confidence': confidence,
            'a_stroke': {'start_idx': a_stroke.start_idx, 'end_idx': a_stroke.end_idx,
                         'start_price': float(a_stroke.start_price), 'end_price': float(a_stroke.end_price)},
            'zs_a': {'low': float(zs_a.low), 'high': float(zs_a.high), 'center': float(zs_a.center)},
            'b_stroke': {'start_idx': b_stroke.start_idx, 'end_idx': b_stroke.end_idx,
                         'start_price': float(b_stroke.start_price), 'end_price': float(b_stroke.end_price)},
            'zs_b': {'low': float(zs_b.low), 'high': float(zs_b.high), 'center': float(zs_b.center)},
            'c_stroke': {'start_idx': c_stroke.start_idx, 'end_idx': c_stroke.end_idx,
                         'start_price': float(c_stroke.start_price), 'end_price': float(c_stroke.end_price)},
            'macd_area_ratio': round(area_ratio, 4),
            'reason': reason,
        }

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
        self.sell_plan = []
    
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

        # [P1-#20] 第一类买点精确入场位
        if buy_points and buy_points[0].type == 'first_buy' and divergence:
            buy_points[0] = self._calculate_first_buy_exact_entry(buy_points[0], divergence)

        # [P1-#21] 三个卖出条件
        recent_close = None
        if strokes:
            recent_close = float(strokes[-1].end_price)
        self.sell_plan = self._generate_sell_plan(divergence, zhongshu_list, strokes, recent_close or 0)

        return buy_points, sell_points
    
    def _find_second_points(self, strokes: List[Stroke],
                           existing_buy: List[BuySellPoint],
                           existing_sell: List[BuySellPoint]) -> Dict[str, List]:
        """
        [P1-#20] 识别第二类买卖点（增强版）

        第二类买点：第一类买点后上涨，回调不创新低。
        增强逻辑：
        - second_buy 必须形成在第一类买点之后
        - 回调不创新低：next_stroke.end_price > first_buy_price
        - 确认条件：回调结束后，有新的一笔上涨启动（确认信号）
        - 置信度 = 0.8 * first_buy.confidence（上限 0.75）
        """
        second_buy = []
        second_sell = []

        if existing_buy:
            first_buy = existing_buy[0]
            first_buy_idx = first_buy.position.get('idx', 0)
            first_buy_price = first_buy.position.get('price', 0)
            base_confidence = min(0.8 * first_buy.confidence, 0.75)

            # 只找第一类买点后的第一个有效配对
            for i, stroke in enumerate(strokes):
                if stroke.start_idx <= first_buy_idx:
                    continue
                if stroke.direction == 'up' and i < len(strokes) - 2:
                    next_stroke = strokes[i + 1]
                    if next_stroke.direction == 'down' and next_stroke.end_price > first_buy_price:
                        # 确认信号：回调结束后有一笔上涨启动
                        confirm_stroke = strokes[i + 2] if i + 2 < len(strokes) else None
                        confirmed = confirm_stroke is not None and confirm_stroke.direction == 'up'
                        confidence = base_confidence + (0.1 if confirmed else 0.0)
                        second_buy.append(BuySellPoint(
                            type='second_buy',
                            confidence=min(confidence, 0.75),
                            position={
                                'idx': next_stroke.end_idx,
                                'price': next_stroke.end_price,
                                'date': next_stroke.end_date
                            },
                            reason='回调不创新低' + ('，上涨确认' if confirmed else '')
                        ))
                        break  # 只识别一次

        if existing_sell:
            first_sell = existing_sell[0]
            first_sell_idx = first_sell.position.get('idx', 0)
            first_sell_price = first_sell.position.get('price', 0)
            base_confidence = min(0.8 * first_sell.confidence, 0.75)

            # 只找第一类卖点后的第一个有效配对
            for i, stroke in enumerate(strokes):
                if stroke.start_idx <= first_sell_idx:
                    continue
                if stroke.direction == 'down' and i < len(strokes) - 2:
                    next_stroke = strokes[i + 1]
                    if next_stroke.direction == 'up' and next_stroke.end_price < first_sell_price:
                        confirm_stroke = strokes[i + 2] if i + 2 < len(strokes) else None
                        confirmed = confirm_stroke is not None and confirm_stroke.direction == 'down'
                        confidence = base_confidence + (0.1 if confirmed else 0.0)
                        second_sell.append(BuySellPoint(
                            type='second_sell',
                            confidence=min(confidence, 0.75),
                            position={
                                'idx': next_stroke.end_idx,
                                'price': next_stroke.end_price,
                                'date': next_stroke.end_date
                            },
                            reason='反弹不创新高' + ('，下跌确认' if confirmed else '')
                        ))
                        break  # 只识别一次

        return {'buy': second_buy, 'sell': second_sell}
    
    def _find_third_points(self, strokes: List[Stroke],
                          zhongshu_list: List[Zhongshu]) -> Dict[str, List]:
        """
        [P1-#20] 识别第三类买卖点（增强版）

        第三类买点：上涨后回调不进入中枢（回调低点 > 中枢.high）
        第三类卖点：下跌后反弹不进入中枢（反弹高点 < 中枢.low）

        - "不进入" 的含义：回调/反弹不重新进入中枢区间
        - 置信度根据回调深度计算：<50%中枢宽度 -> 0.7, 否则 -> 0.6
        只搜索最新中枢 end_idx 之后的笔，避免全局历史堆积。
        """
        third_buy = []
        third_sell = []
        
        if not zhongshu_list:
            return {'buy': third_buy, 'sell': third_sell}
        
        latest_zhongshu = zhongshu_list[-1]
        zhongshu_width = latest_zhongshu.high - latest_zhongshu.low
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
                    # "不进入中枢"意味着回调低点 > 中枢.high
                    if next_stroke.end_price > latest_zhongshu.high:
                        pullback_depth = abs(next_stroke.end_price - latest_zhongshu.high)
                        if zhongshu_width > 0 and pullback_depth < 0.5 * zhongshu_width:
                            confidence = 0.7
                            depth_note = '回调深度小于中枢宽50%'
                        else:
                            confidence = 0.6
                            depth_note = '回调深度大于中枢宽50%'
                        third_buy.append(BuySellPoint(
                            type='third_buy',
                            confidence=confidence,
                            position={
                                'idx': next_stroke.end_idx,
                                'price': next_stroke.end_price,
                                'date': next_stroke.end_date
                            },
                            reason=f'回调不进入中枢,[{latest_zhongshu.low:.2f},{latest_zhongshu.high:.2f}],{depth_note}',
                            zhongshu=latest_zhongshu
                        ))
            
            # 第三类卖点：下跌后反弹
            elif stroke.direction == 'down':
                next_stroke = strokes[i + 1]
                if next_stroke.direction == 'up':
                    # 反弹高点在中枢下方 = 第三类卖点
                    if next_stroke.end_price < latest_zhongshu.low:
                        pullback_depth = abs(latest_zhongshu.low - next_stroke.end_price)
                        if zhongshu_width > 0 and pullback_depth < 0.5 * zhongshu_width:
                            confidence = 0.7
                            depth_note = '反弹深度小于中枢宽50%'
                        else:
                            confidence = 0.6
                            depth_note = '反弹深度大于中枢宽50%'
                        third_sell.append(BuySellPoint(
                            type='third_sell',
                            confidence=confidence,
                            position={
                                'idx': next_stroke.end_idx,
                                'price': next_stroke.end_price,
                                'date': next_stroke.end_date
                            },
                            reason=f'反弹不进入中枢,[{latest_zhongshu.low:.2f},{latest_zhongshu.high:.2f}],{depth_note}',
                            zhongshu=latest_zhongshu
                        ))
        
        return {'buy': third_buy, 'sell': third_sell}

    def _calculate_first_buy_exact_entry(self, first_buy: BuySellPoint, divergence: Divergence) -> BuySellPoint:
        """
        [P1-#20] 第一类买点精确入场位计算

        如果背驰已被MACD确认:
        - 入场价格 = 背驰位置的价格（背驰点）
        - 在 reason 中补充MACD面积比详情
        """
        if divergence is None:
            return first_buy

        # 直接使用背驰位置的价格作为入场参考
        entry_price = first_buy.position.get('price', 0)

        details = divergence.details or {}
        if divergence.type == 'trend_backtesting':
            macd_ratio = details.get('macd_area_ratio', 'unknown')
            entry_reason = first_buy.reason + f" | MACD面积比={macd_ratio}, 入场={entry_price:.2f}"
        elif divergence.type == 'consolidation':
            down_amp = details.get('down_amplitude', 0)
            up_amp = details.get('prev_up_amplitude', 0)
            ratio = f"{down_amp / up_amp:.2f}" if up_amp else 'unknown'
            entry_reason = first_buy.reason + f" | 回调/离开幅度比={ratio}, 入场={entry_price:.2f}"
        elif divergence.type == 'zhongshu':
            entry_reason = first_buy.reason + f" | 中枢破坏背驰, 入场={entry_price:.2f}"
        else:
            entry_reason = first_buy.reason

        return BuySellPoint(
            type=first_buy.type,
            confidence=first_buy.confidence,
            position=first_buy.position,
            reason=entry_reason
        )

    def _generate_sell_plan(self, divergence: Divergence, zhongshu_list: List, strokes: List, current_price: float) -> List[Dict]:
        """
        [P1-#21] 三个卖出条件（缠论版）

        本级别背驰卖1/3 + 次级别反弹不破中枢卖1/3 + 跌破中枢卖剩余

        Returns: List of sell step dicts
        """
        steps = []
        latest_zs = zhongshu_list[-1] if zhongshu_list else None

        if divergence and divergence.direction == 'down':
            # Step 1: 背驰卖1/3
            steps.append({
                'step': 1,
                'action': '卖出1/3',
                'condition': '趋势背驰出现',
                'price': float(divergence.position.get('price', current_price)),
                'confidence': 0.80,
                'reason': f"本级别{divergence.type}背驰出现, 背驰力度={divergence.confidence:.2f}",
            })

            # Step 2: 反弹不破中枢卖1/3 (need at least one stroke after the divergence)
            if latest_zs:
                steps.append({
                    'step': 2,
                    'action': '卖出1/3',
                    'condition': '次级别反弹不破中枢上沿',
                    'target': f"反弹至{latest_zs.high:.2f}附近不过上沿则卖出",
                    'confidence': 0.70,
                    'reason': f"次级别反弹确认, 中枢上沿={latest_zs.high:.2f}构成压制",
                })

            # Step 3: 跌破中枢卖剩余
            if latest_zs:
                steps.append({
                    'step': 3,
                    'action': '清仓',
                    'condition': '跌破中枢下沿',
                    'price': float(latest_zs.low),
                    'confidence': 0.90,
                    'reason': f"跌破中枢下沿{latest_zs.low:.2f}, 趋势完全转空",
                })

        return steps


class ChanlunAnalyzer:
    """
    完整缠论分析器

    整合所有缠论组件，提供完整的分析流程

    WINDOW_CONFIG (P1-#29):
        'lookback_period': 120  — 回看周期从 60→120，提高背驰/买卖点判断的数据窗口长度
        'min_klines': 4, 'min_stroke_count': 3, 'min_segment_count': 3  — 结构识别参数不变
        数据最短校验: analyze() 入口≥30K线(结构检测), generate_insights() 入口≥120K线(全量分析)
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
            lookback_period=self.config.get('lookback_period', 120)
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
            'lookback_period': 120,  # 回看周期 (P1-#29: ⬆60→120)
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
        
        # 7. 背驰判断（支持 MACD 面积确认）
        self.divergence = self.divergence_detector.detect(
            self.strokes,
            self.zhongshu_list,
            closes=df['close'].values if 'close' in df.columns else None
        )
        
        # 8. 买卖点识别
        self.buy_points, self.sell_points = self.buy_sell_detector.find(
            self.strokes,
            self.zhongshu_list,
            self.divergence
        )

        # 9. 缠论定理体系校验
        self.theorem_check = ChanlunTheoremValidator().validate(
            self.segments, self.zhongshu_list, self.strokes,
            df['close'].values if 'close' in df.columns else None
        )

        # 10. 中枢内因子动态切换
        self.factor_switch = ZhongshuFactorSwitch()
        zs = self.zhongshu_list[-1] if self.zhongshu_list else None
        if zs and self.klines:
            latest_close = self.klines[-1].close
            self.factor_position = self.factor_switch.get_position(latest_close, zs)
            self.factor_weight_adj = self.factor_switch.adjust_weight(self.factor_position)
            self.selected_factors = self.factor_switch.select_factors(self.factor_position)
        else:
            self.factor_position = 'none'
            self.factor_weight_adj = 1.0
            self.selected_factors = {'factors': [], 'strategy': '无中枢'}

        # 11. 未确认分型检测（K线尾部潜在转向信号）
        last_confirmed_idx = -1
        if self.fractals:
            last_confirmed_idx = self.fractals[-1].idx
        self.pending_judgment = self.fractal_detector.get_last_unconfirmed_fractal(
            klines_no_contain, last_confirmed_idx
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
            'summary': self._generate_summary(),
            'theorem_check': self.theorem_check,
            'factor_switch': {
                'position': self.factor_position,
                'weight_adjustment': self.factor_weight_adj,
                'selected_factors': self.selected_factors
            },
            'pending_judgment': self.pending_judgment
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
    def score(analysis_result: Dict, latest_close: float = None,
              market_context: Optional[Dict] = None) -> Dict:
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

        # ── 市场上下文评分调整 ──
        if market_context:
            # 换手率调整: 高换手时信号置信度更高
            turnover = market_context.get('turnover_rate')
            if turnover is not None:
                if turnover > 10:
                    score += 5
                    details.append(f"换手率{turnover:.1f}% > 10%, 信号活跃(+5)")
                elif turnover > 5:
                    score += 3
                    details.append(f"换手率{turnover:.1f}% > 5%, 资金活跃(+3)")

            # 资金流向调整: 大单净流入增强信号
            net_lg = market_context.get('net_lg_amount')
            if net_lg is not None:
                if net_lg > 0:
                    score += 3
                    details.append(f"近5日大单净流入{net_lg:.0f}, 主力看多(+3)")
                elif net_lg < 0:
                    score -= 3
                    details.append(f"近5日大单净流出{abs(net_lg):.0f}, 主力看空(-3)")

            # 指数环境调整
            idx_condition = market_context.get('index_condition')
            if idx_condition:
                if idx_condition == 'POOR':
                    score -= 5
                    details.append(f"大盘环境偏弱, 信号减仓(-5)")
                elif idx_condition == 'GOOD':
                    score += 3
                    details.append(f"大盘环境偏强, 信号增强(+3)")

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
                if len(df) < 120:
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


class ChanlunTheoremValidator:
    """
    缠论11个定理体系校验

    对已识别的线段、中枢、笔结构进行定理一致性与健康度检查。
    每个定理包含：passed（是否通过）、score（0~1 健康分）、issues（问题列表）、description（定理描述）。
    """

    def __init__(self):
        self._results = {}

    def validate(self, segments, zhongshu_list, strokes, closes) -> Dict:
        """
        运行全部11个定理校验

        Args:
            segments: Segment 列表
            zhongshu_list: Zhongshu 列表
            strokes: Stroke 列表
            closes: np.ndarray 收盘价数组（可选）

        Returns:
            {
                'summary': {'passed': int, 'total': int, 'overall_score': float},
                'details': {t1: {...}, t2: {...}, ...}
            }
        """
        self._results = {}
        self._results['t1'] = self._check_t1(segments)
        self._results['t2'] = self._check_t2(strokes)
        self._results['t3'] = self._check_t3(segments, zhongshu_list)
        self._results['t4'] = self._check_t4(segments, zhongshu_list, closes)
        self._results['t5'] = self._check_t5(zhongshu_list)
        self._results['t6'] = self._check_t6(segments)
        self._results['t7'] = self._check_t7(segments, zhongshu_list)
        self._results['t8'] = self._check_t8(segments, zhongshu_list, closes)
        self._results['t9'] = self._check_t9(strokes, segments)
        self._results['t10'] = self._check_t10(strokes)
        self._results['t11'] = self._check_t11(zhongshu_list)

        total = len(self._results)
        passed = sum(1 for v in self._results.values() if v.get('passed'))
        overall_score = sum(v.get('score', 0) for v in self._results.values()) / total

        return {
            'summary': {
                'passed': passed,
                'total': total,
                'overall_score': round(overall_score, 4),
            },
            'details': self._results,
        }

    def _check_t1(self, segments) -> Dict:
        """
        T1: 走势必完美（走势必完整）
        每个线段至少包含3笔，否则走势不完整。
        """
        desc = 'T1 走势必完美：每个线段至少包含3笔'
        if not segments:
            return {'passed': False, 'score': 0.0, 'issues': ['无线段数据'], 'description': desc}
        issues = []
        bad_count = 0
        for i, seg in enumerate(segments):
            n = len(seg.strokes) if seg.strokes else 0
            if n < 3:
                bad_count += 1
                issues.append(f"第{i}段(seg[{seg.start_idx},{seg.end_idx}])笔数={n}<3")
        passed = bad_count == 0
        score = max(0.0, 1.0 - bad_count / len(segments))
        return {'passed': passed, 'score': round(score, 2), 'issues': issues, 'description': desc}

    def _check_t2(self, strokes) -> Dict:
        """
        T2: 级别递归一致性
        笔的幅度应该一致，不应出现某一笔幅度远大于平均（>2x）或远小于（<0.3x）。
        """
        desc = 'T2 级别递归：笔幅度应一致(均值0.3x~2x区间内)'
        if not strokes:
            return {'passed': False, 'score': 0.0, 'issues': ['无笔数据'], 'description': desc}
        amps = [s.amplitude for s in strokes if s.amplitude > 0]
        if not amps:
            return {'passed': False, 'score': 0.0, 'issues': ['所有笔幅度为0'], 'description': desc}
        mean_amp = np.mean(amps)
        if mean_amp == 0:
            return {'passed': False, 'score': 0.0, 'issues': ['笔幅度均值为0'], 'description': desc}
        issues = []
        bad_count = 0
        for s in strokes:
            if s.amplitude == 0:
                continue
            ratio = s.amplitude / mean_amp
            if ratio < 0.3 or ratio > 2.0:
                bad_count += 1
                issues.append(f"笔[{s.start_idx},{s.end_idx}]幅度比={ratio:.3f}, 超[0.3,2.0]")
        passed = bad_count == 0
        # 允许少量异常 -> 扣分
        score = max(0.0, 1.0 - bad_count / len(amps))
        return {'passed': passed, 'score': round(score, 2), 'issues': issues, 'description': desc}

    def _check_t3(self, segments, zhongshu_list) -> Dict:
        """
        T3: 中枢破坏
        第三段离开中枢且不再回到中枢区间。
        """
        desc = 'T3 中枢破坏：第3段突破中枢并停留在外'
        if not zhongshu_list:
            return {'passed': True, 'score': 1.0, 'issues': [], 'description': desc + '（无中枢，自动通过）'}
        if len(segments) < 3:
            return {'passed': False, 'score': 0.0, 'issues': ['线段不足3段'], 'description': desc}
        issues = []
        bad_count = 0
        for zs in zhongshu_list:
            by_idx = sorted([s for s in segments if hasattr(s, 'start_idx')], key=lambda x: x.start_idx)
            for s in by_idx:
                if s.start_idx >= zs.start_idx and s.end_idx <= zs.end_idx:
                    continue
                if s.start_idx > zs.end_idx:
                    # 检查离开段的 end_price 是否不在中枢内
                    if zs.contains_price(s.end_price):
                        bad_count += 1
                        issues.append(f"中枢[{zs.start_idx},{zs.end_idx}]之后段[{s.start_idx},{s.end_idx}]回到中枢")
        passed = bad_count == 0
        score = max(0.0, 1.0 - bad_count * 0.15)
        return {'passed': passed, 'score': round(score, 2), 'issues': issues, 'description': desc}

    def _check_t4(self, segments, zhongshu_list, closes) -> Dict:
        """
        T4: 背驰与转折
        背驰发生后，价格应返回最近中枢。
        """
        desc = 'T4 背驰与转折：背驰后价格返回最近中枢'
        if not zhongshu_list or segments is None or len(segments) < 2:
            return {'passed': True, 'score': 1.0, 'issues': [], 'description': desc + '（数据不足，跳过）'}
        issues = []
        latest_zs = zhongshu_list[-1]
        # 找到中枢之后的最后一个段
        after_zs = [s for s in segments if s.start_idx > latest_zs.end_idx]
        if not after_zs:
            return {'passed': True, 'score': 1.0, 'issues': [], 'description': desc + '（无中枢后数据）'}
        last_seg = after_zs[-1]
        # 检查最后一个段是否回到了中枢范围
        back = (last_seg.end_price >= latest_zs.low and last_seg.end_price <= latest_zs.high)
        if not back:
            issues.append(f"末段[{last_seg.start_idx},{last_seg.end_idx}]价格{last_seg.end_price:.2f}未回中枢[{latest_zs.low:.2f},{latest_zs.high:.2f}]")
        score = 1.0 if back else 0.5
        return {'passed': back, 'score': score, 'issues': issues, 'description': desc}

    def _check_t5(self, zhongshu_list) -> Dict:
        """
        T5: 买卖点级别对应
        买卖点必须对应中枢级别。
        """
        desc = 'T5 买卖点级别对应：买卖点应与中枢级别对应'
        if not zhongshu_list:
            return {'passed': True, 'score': 1.0, 'issues': [], 'description': desc + '（无中枢）'}
        # 检查是否有正常的中枢区间，视为级别已确认
        issues = []
        for i, zs in enumerate(zhongshu_list):
            if zs.range_width is None or zs.range_width < 0.01:
                issues.append(f"中枢{i}区间宽度过小={zs.range_width}")
        passed = len(issues) == 0
        score = 1.0 if passed else 0.5
        return {'passed': passed, 'score': score, 'issues': issues, 'description': desc}

    def _check_t6(self, segments) -> Dict:
        """
        T6: 同级别分解
        同级别走势的线段笔数应相近（CV < 0.5）。
        """
        desc = 'T6 同级别分解：各线段笔数应相近(CV<0.5)'
        if not segments:
            return {'passed': False, 'score': 0.0, 'issues': ['无线段'], 'description': desc}
        stroke_counts = np.array([len(s.strokes) if s.strokes else 0 for s in segments])
        if len(stroke_counts) < 2:
            return {'passed': True, 'score': 1.0, 'issues': [], 'description': desc + '（仅一段）'}
        mean = np.mean(stroke_counts)
        if mean == 0:
            return {'passed': False, 'score': 0.0, 'issues': ['所有线段笔数为0'], 'description': desc}
        cv = np.std(stroke_counts) / mean
        issues = []
        if cv >= 0.5:
            issues.append(f"线段笔数CV={cv:.3f}>=0.5，笔数分布差异大: {stroke_counts.tolist()}")
        score = max(0.0, 1.0 - cv)
        return {'passed': cv < 0.5, 'score': round(score, 2), 'issues': issues, 'description': desc}

    def _check_t7(self, segments, zhongshu_list) -> Dict:
        """
        T7: 趋势延伸与结束
        最后一个中枢被破坏 + 反向线段确认。
        """
        desc = 'T7 趋势延伸与结束：末中枢被破坏+反向段确认'
        if not zhongshu_list or len(segments) < 2:
            return {'passed': True, 'score': 1.0, 'issues': [], 'description': desc + '（数据不足）'}
        issues = []
        latest_zs = zhongshu_list[-1]
        after_zs = [s for s in segments if s.start_idx > latest_zs.end_idx]
        if not after_zs:
            issues.append('最后一个中枢后无线段，趋势是否结束待确认')
            score = 0.5
        else:
            first_after = after_zs[0]
            outside = not latest_zs.contains_price(first_after.end_price)
            if not outside:
                issues.append(f"中枢后首段[{first_after.start_idx},{first_after.end_idx}]未突破中枢")
                score = 0.4
            else:
                score = 1.0
        passed = len(issues) == 0
        return {'passed': passed, 'score': round(score, 2), 'issues': issues, 'description': desc}

    def _check_t8(self, segments, zhongshu_list, closes) -> Dict:
        """
        T8: 多级别联立（占位）
        需要多级别数据支持。当前返回占位通过。
        """
        desc = 'T8 多级别联立：占位实现，需要多级别数据'
        return {'passed': True, 'score': 1.0, 'issues': ['需多级别数据(日/周/月联立)'], 'description': desc}

    def _check_t9(self, strokes, segments) -> Dict:
        """
        T9: 特征序列（占位）
        关联 P1-#8 特征序列缺口处理逻辑。当前简化检查：特征序列中的反向笔是否有跳空缺口。
        """
        desc = 'T9 特征序列：关联P1-#8特征序列缺口处理（占位实现）'
        if not segments:
            return {'passed': True, 'score': 1.0, 'issues': ['无线段'], 'description': desc}
        issues = []
        gap_count = 0
        for seg in segments:
            seg_strokes = seg.strokes or []
            for j in range(1, len(seg_strokes)):
                prev_s = seg_strokes[j - 1]
                curr_s = seg_strokes[j]
                if prev_s.direction != curr_s.direction:
                    if seg.direction == 'up' and curr_s.direction == 'down':
                        if curr_s.end_price > prev_s.start_price:
                            gap_count += 1
                    elif seg.direction == 'down' and curr_s.direction == 'up':
                        if curr_s.end_price < prev_s.start_price:
                            gap_count += 1
        if gap_count > 0:
            issues.append(f"特征序列跳空缺口数={gap_count}")
        score = max(0.0, 1.0 - gap_count * 0.1)
        return {'passed': True, 'score': round(score, 2), 'issues': issues, 'description': desc}

    def _check_t10(self, strokes) -> Dict:
        """
        T10: 动力结构
        比较相邻同方向笔的力度，检查是否出现力度递减（背驰前兆）。
        """
        desc = 'T10 动力结构：相邻同向笔力度比较'
        if not strokes or len(strokes) < 4:
            return {'passed': True, 'score': 1.0, 'issues': ['笔不足'], 'description': desc}
        up_strokes = [s for s in strokes if s.direction == 'up']
        down_strokes = [s for s in strokes if s.direction == 'down']
        issues = []
        weakening = 0
        for group in [up_strokes, down_strokes]:
            for i in range(1, len(group)):
                amp_prev = group[i - 1].amplitude
                amp_curr = group[i].amplitude
                if amp_prev > 0 and amp_curr < amp_prev * 0.6:
                    weakening += 1
                    issues.append(f"同向笔力度减弱: {group[i-1]} -> {group[i]}")
        score = max(0.0, 1.0 - weakening * 0.15)
        passed = weakening == 0
        return {'passed': passed, 'score': round(score, 2), 'issues': issues, 'description': desc}

    def _check_t11(self, zhongshu_list) -> Dict:
        """
        T11: 走势类型转换
        用中枢数量判断走势类型：1个中枢=盘整，>=2个中枢=趋势。
        """
        desc = 'T11 走势类型转换：中枢数判走势类型'
        if not zhongshu_list:
            return {'passed': True, 'score': 1.0, 'issues': ['无中枢=无走势类型'], 'description': desc}
        n = len(zhongshu_list)
        if n == 1:
            trend_type = 'pan_zheng'  # 盘整
        else:
            trend_type = 'trend'  # 趋势
        issues = []
        # 检查中枢的方向是否一致（趋势时）
        if n >= 2:
            directions = set()
            for zs in zhongshu_list:
                if hasattr(zs, 'direction') and zs.direction:
                    directions.add(zs.direction)
            if len(directions) > 1:
                issues.append(f"多中枢方向不一致({directions})，走势类型判断需谨慎")
        score = 0.8 if issues else 1.0
        return {'passed': len(issues) == 0, 'score': score, 'issues': issues, 'description': desc + f'（{trend_type}）'}


class ZhongshuFactorSwitch:
    """
    中枢内因子动态切换

    根据价格相对中枢的位置动态选择适合的因子类别：
    - inside:   价格在中枢内部 → 反转因子、RSI均值回归、BOLL收口突破
    - above:    价格在中枢上方 → 动量因子、MACD趋势跟踪、均线多头排列
    - below:    价格在中枢下方 → 超卖因子、RSI超卖反弹、支撑位反弹
    - none:     无中枢 → 常规因子
    """

    FACTOR_GROUPS = {
        'inside': ['反转因子', 'RSI均值回归', 'BOLL收口突破'],
        'above': ['动量因子', 'MACD趋势跟踪', '均线多头排列'],
        'below': ['超卖因子', 'RSI超卖反弹', '支撑位反弹'],
    }

    def get_position(self, price: float, zhongshu) -> str:
        """
        判断价格相对中枢的位置

        Args:
            price: 当前价格
            zhongshu: Zhongshu 对象

        Returns:
            'inside' | 'above' | 'below' | 'none'
        """
        if zhongshu is None:
            return 'none'
        if hasattr(zhongshu, 'contains_price') and zhongshu.contains_price(price):
            return 'inside'
        if hasattr(zhongshu, 'is_above') and zhongshu.is_above(price):
            return 'above'
        if hasattr(zhongshu, 'is_below') and zhongshu.is_below(price):
            return 'below'
        return 'none'

    def select_factors(self, position: str, base_factors: List[str] = None) -> Dict:
        """
        根据位置选取因子类别

        Args:
            position: 'inside' / 'above' / 'below' / 'none'
            base_factors: 基础因子列表（可选）

        Returns:
            {'factors': [...], 'strategy': '...'}
        """
        base = base_factors or []
        factors = self.FACTOR_GROUPS.get(position, [])
        strategy_map = {
            'inside': '中枢内震荡，偏均值回归',
            'above': '中枢上方运行，偏趋势跟踪',
            'below': '中枢下方运行，偏超卖反弹',
            'none': '无中枢，使用常规因子',
        }
        return {
            'factors': factors + base,
            'strategy': strategy_map.get(position, '未知位置'),
        }

    def adjust_weight(self, position: str) -> float:
        """
        根据位置调整权重

        inside=0.85（中枢内震荡，降低仓位）
        above=1.10（突破确认，适当加仓）
        below=1.05（中枢下方，适度加仓博反弹）
        none=1.00（无中枢，保持中性）
        """
        weights = {'inside': 0.85, 'above': 1.10, 'below': 1.05, 'none': 1.0}
        return weights.get(position, 1.0)

    def get_adjustment_hint(self, position: str) -> str:
        """返回中文提示文本"""
        hints = {
            'inside': '价格在中枢内部震荡，建议降低仓位等待突破确认',
            'above': '价格在中枢上方运行，突破确认后可适当加仓',
            'below': '价格在中枢下方运行，关注超卖反弹机会',
            'none': '无中枢结构，使用常规分析框架',
        }
        return hints.get(position, '未知位置')
