"""SIG 英文枚举 → 中文映射公共常量（440-SIG素材质量前置修复）

将散落在 dim2/dim3/dim4/dim5 引擎中的英文枚举值统一映射为现状描述用的中文，
避免"均线mixed"这类机翻残留；dim8 归集现状描述时也复用本表。

枚举值域来源核查（2026-09-15）：
  - ma_alignment      : {bullish, bearish, mixed}              (data_daemon.py:3475-3479)
  - chip_concentration: {concentrating, dispersing, stable}     (chip_distribution_service.py:184-188)
  - bociasi signal    : {BUY, WATCH, BEARISH, NEUTRAL, BULLISH} (dim5_emotion_engine)
  - quadrant          : {HH, LL, HL, LH, MM}                    (dim5_emotion_engine)
"""
from __future__ import annotations

# ─────────────────────────────────────────────────────────────
# 均线排列 (ma_alignment)
# ─────────────────────────────────────────────────────────────
MA_ALIGNMENT_CN = {
    'bullish': '多头排列',
    'bearish': '空头排列',
    'mixed': '交织',  # dim2 调用侧拼 f"均线{ma_alignment_cn(...)}"，此处不可再含 '均线'
    '': '无明确排列',
}
# 兼容既有中文写法（dim3_vp_engine.py:4657 曾硬编码 '多头排列'/'空头排列'）
MA_ALIGNMENT_CN_EXT = {**MA_ALIGNMENT_CN, '多头排列': '多头排列', '空头排列': '空头排列'}


def ma_alignment_cn(value) -> str:
    """ma_alignment → 中文现状描述，未知名返回 '均线数据不足' 交由调用方兜底"""
    return MA_ALIGNMENT_CN.get(str(value or '').strip().lower(), str(value or ''))


# ─────────────────────────────────────────────────────────────
# 筹码集中度 (chip_concentration)
# ─────────────────────────────────────────────────────────────
CHIP_CONCENTRATION_CN = {
    'concentrating': '集中',
    'dispersing': '发散',
    'stable': '稳定',
    '': '数据不足',
}


def chip_concentration_cn(value) -> str:
    """chip_concentration → 中文现状描述"""
    return CHIP_CONCENTRATION_CN.get(str(value or '').strip().lower(), str(value or ''))


# ─────────────────────────────────────────────────────────────
# BOCIASI 快/慢线信号 (quick/slow signal)
# ─────────────────────────────────────────────────────────────
BOCIASI_SIGNAL_CN = {
    'BUY': '偏多',
    'BULLISH': '看多',
    'WATCH': '观望',
    'BEARISH': '看空',
    'SELL': '偏空',
    'NEUTRAL': '中性',
}


def bociasi_signal_cn(value) -> str:
    """BOCIASI 信号 → 中文，NEUTRAL 数据不足时保持可读"""
    return BOCIASI_SIGNAL_CN.get(str(value or '').strip().upper(), str(value or 'N/A'))


# ─────────────────────────────────────────────────────────────
# 四象限 (quadrant HH/LL/HL/LH/MM)
# ─────────────────────────────────────────────────────────────
QUADRANT_CN = {
    'HH': '高位高位', 'LH': '低位高位', 'HL': '高位低位',
    'LL': '低位低位', 'MM': '中性',
    '': '中性',
}


def quadrant_cn(value) -> str:
    """四象限 → 中文，未知回退 '中性'（保持与 quadrant 兜底语义一致）"""
    return QUADRANT_CN.get(str(value or '').strip().upper(), '中性')


# ─────────────────────────────────────────────────────────────
# 形态编码 → 中文名（P-1-4 → "缩量回踩均线"，复用 PatternRegistry 官方 label）
# ─────────────────────────────────────────────────────────────
def pattern_code_cn(code) -> str:
    """形态编码 → 中文名；未注册的编码原样返回。复用引擎官方注册表避免重复字典。"""
    try:
        from app.engine.patterns.registry import PatternRegistry
        meta = PatternRegistry().get(str(code or '').strip())
        if meta is None:
            return str(code or '')
        # description 形如 "缩量回踩均线: 上升趋势中缩量回踩..."，取 ':' 前的中文 label
        return meta.description.split(':', 1)[0].strip() if meta.description else str(code)
    except Exception:
        return str(code or '')
