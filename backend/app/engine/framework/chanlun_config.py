"""
缠论策略统一配置 — 参数集中管理

参考: chan.py CChanConfig 设计，本系统4个配置模块的汇总入口
"""
from dataclasses import dataclass, field
from typing import List, Optional


@dataclass
class BiConfig:
    """笔配置"""
    min_klines: int = 4
    min_amplitude_pct: float = 0.0  # 0% = 不按幅度过滤（缠论原文无此条件）
    bi_strict: bool = True
    bi_fx_check: str = 'strict'  # strict / totally / loss / half
    bi_allow_sub_peak: bool = True
    bi_end_is_peak: bool = True
    gap_as_kl: bool = True


@dataclass
class SegmentConfig:
    """线段配置"""
    min_stroke_count: int = 3
    seg_algo: str = 'chan'  # chan / 1+1 / break
    left_seg_method: str = 'peak'  # all / peak


@dataclass
class ZhongshuConfig:
    """中枢配置"""
    min_segment_count: int = 3
    min_width: float = 1.0
    zs_combine: bool = True
    zs_combine_mode: str = 'zs'  # zs(区间重叠) / peak(K线重叠)
    zs_algo: str = 'normal'  # normal(段内) / over_seg(跨段) / auto


@dataclass
class DivergenceConfig:
    """背驰配置"""
    lookback_period: int = 120
    divergence_rate: float = 0.9
    min_zs_cnt: int = 1
    macd_algo: str = 'area'  # area / peak / full_area / slope / amp / diff / volume
    bsp1_only_multibi_zs: bool = True


@dataclass
class BuySellConfig:
    """买卖点配置"""
    bs_type: str = '1,2,3a,3b'
    bsp2_follow_1: bool = True
    bsp3_follow_1: bool = True
    bsp2s_follow_2: bool = False
    bsp3_peak: bool = False
    max_bs2_rate: float = 0.618
    bs1_peak: bool = True
    strict_bsp3: bool = False
    bsp3a_max_zs_cnt: int = 1


@dataclass
class MultiLevelConfig:
    """多级别联立配置"""
    enabled: bool = True
    levels: tuple = ('weekly', 'daily', 'hourly')
    lookback: dict = field(default_factory=lambda: {
        'weekly': 260, 'daily': 130, 'hourly': 60,
    })
    min_segments: dict = field(default_factory=lambda: {
        'weekly': 3, 'daily': 3, 'hourly': 2,
    })


@dataclass
class ChanlunConfig:
    """缠论总配置 — CChanConfig 风格统一入口"""
    bi: BiConfig = field(default_factory=BiConfig)
    segment: SegmentConfig = field(default_factory=SegmentConfig)
    zhongshu: ZhongshuConfig = field(default_factory=ZhongshuConfig)
    divergence: DivergenceConfig = field(default_factory=DivergenceConfig)
    buy_sell: BuySellConfig = field(default_factory=BuySellConfig)
    multi_level: MultiLevelConfig = field(default_factory=MultiLevelConfig)

    @classmethod
    def default(cls) -> 'ChanlunConfig':
        return cls()

    @classmethod
    def from_dict(cls, d: dict) -> 'ChanlunConfig':
        """从字典更新配置（保留未指定的默认值）"""
        cfg = cls.default()
        if 'bi' in d:
            for k, v in d['bi'].items():
                if hasattr(cfg.bi, k):
                    setattr(cfg.bi, k, v)
        if 'segment' in d:
            for k, v in d['segment'].items():
                if hasattr(cfg.segment, k):
                    setattr(cfg.segment, k, v)
        if 'zhongshu' in d:
            for k, v in d['zhongshu'].items():
                if hasattr(cfg.zhongshu, k):
                    setattr(cfg.zhongshu, k, v)
        if 'divergence' in d:
            for k, v in d['divergence'].items():
                if hasattr(cfg.divergence, k):
                    setattr(cfg.divergence, k, v)
        if 'buy_sell' in d:
            for k, v in d['buy_sell'].items():
                if hasattr(cfg.buy_sell, k):
                    setattr(cfg.buy_sell, k, v)
        if 'multi_level' in d:
            for k, v in d['multi_level'].items():
                if hasattr(cfg.multi_level, k):
                    setattr(cfg.multi_level, k, v)
        return cfg
