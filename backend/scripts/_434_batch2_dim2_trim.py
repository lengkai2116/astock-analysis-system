# -*- coding: utf-8 -*-
"""434号 批次2：dim2 删 4 个内联区块（:29-:3819）改 import framework + shared。

用法：python scripts/_434_batch2_dim2_trim.py
（源文件已备份 /tmp/dim2_backup_batch2.py）
"""
from pathlib import Path

P = Path("app/opportunity_atlas/dimensions/dim2_structure_engine.py")
src = P.read_text(encoding="utf-8").splitlines()

# 校验锚点
assert src[28].startswith("# === chanlun_config.py ==="), src[28]
assert src[3815].startswith("# ═"), src[3815]
assert src[3819].startswith("class Dim2StructureEngine"), src[3819]

NEW_IMPORT = [
    "",
    "# 434号 批次2（2026-09-14）：删除内联 vendored 缠论 4 区块，改 import framework 权威 + shared 共享服务。",
    "# 缠论能力全局单一代码源（framework）；支撑阻力统一走 shared_support_resistance。",
    "from app.engine.framework.chanlun_config import (",
    "    BiConfig, SegmentConfig, ZhongshuConfig, DivergenceConfig,",
    "    BuySellConfig, MultiLevelConfig, ChanlunConfig,",
    ")",
    "from app.engine.framework.chanlun_level_validator import ChanlunLevelValidator",
    "from app.engine.framework.chanlun_strategy import (",
    "    KLine, Fractal, Stroke, Segment, Zhongshu, Divergence, BuySellPoint,",
    "    KLineMerger, FractalDetector, StrokeBuilder, SegmentAnalyzer, ZhongshuAnalyzer,",
    "    BiZhongshuFinder, DivergenceDetector, BuySellPointDetector, ChanlunAnalyzer,",
    "    analyze_chanlun, get_chanlun_tags, ChanlunScorer, ChanlunAlphaModel,",
    "    SignalFusion, StrategyValidationLayer, ChanlunTheoremValidator, ZhongshuFactorSwitch,",
    "    calc_macd, _load_precomputed_macd, _MACD_PRECOMPUTED_CACHE,",
    ")",
    "from app.engine.framework.trend_structure_detector import TrendStructureDetector",
    "from app.opportunity_atlas.dimensions.shared_support_resistance import calc_support_resistance",
    "",
]

# 保留文件头 :0-:27（docstring+imports+logger+空行），删除 :28..:3814（4 区块），保留 :3815 起（第2维引擎）
head = src[:28]          # 0..27（含 :27 空行）
tail = src[3815:]        # 3815..end（含 第2维引擎 分隔注释）
assert head[-1] == "", f"head ends with {head[-1]!r}"
assert tail[0].startswith("# ═"), tail[0]

new_src = head + NEW_IMPORT + tail
P.write_text("\n".join(new_src), encoding="utf-8")
print(f"OK: {len(src)} -> {len(new_src)} 行（删 {len(src) - len(new_src)} 行）")
