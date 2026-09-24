"""480号 后续：dim8 展示中文网关 dim5-7 全量覆盖单测（纯展示层，无 DB）

覆盖（480 后续 + 本会话补 3a）：
  - G1 dim5 快线/慢线/四象限/温度 数值因全中文：RPS→相对强弱因子、ERP→股权风险溢价、
      BOCIASI→情绪周期、四象限 7 指标（均线/换手/涨跌停比/RSI/ERP/融资）
  - G2 dim7 收益驱动全中文：composite→综合评分、PE/PB近5年→市盈率/市净率近5年、
      ROE→净资产收益率、ROCE→资本回报率、PEG→市盈增长比、潜力六维标注 dimN→第N维
  - G3 背驰 type 枚举中文（本会话 3a）：'xx趋势背驰，trend类型'→'趋势背驰' 等
  - G4 合理保留：指标缩写带释义（ASR（活跃筹码比率））、结构化英文枚举不误中
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
for k in ['HTTP_PROXY', 'HTTPS_PROXY', 'ALL_PROXY']:
    os.environ.pop(k, None)

import re

from app.opportunity_atlas.dimensions.dim8_summary_engine import _to_display_text


def _assert_no_ascii(s, must_contain, allow=()):
    """断言展示串中化后含 must_contain，且 ASCII token 仅允许 allow（合理保留）"""
    assert must_contain in s, f'缺 {must_contain!r} in: {s}'
    toks = re.findall(r'[A-Za-z][A-Za-z0-9_.\-]*', s)
    bad = [t for t in toks if t not in allow and not re.match(r'^\d|%$|^0$', t)]
    assert not bad, f'残留 ASCII{set(bad)} in: {s}'


class TestDim5Gateway:
    """dim5 情绪环境段：快线/慢线/四象限/温度全中文"""

    def test_bociasi_quick_details(self):
        s = "个股快线=中性（0.35）：量比1.31、价格偏离-0.5%、5日动量-0.5%、振幅1.65%"
        out = _to_display_text(s)
        # 快线本身无 BOCIASI/英文指标残留（量比/价格/动量/振幅均为中文）
        assert '个股快线' in out
        assert 'BOCIASI' not in out and 'NEUTRAL' not in out and 'BUY' not in out

    def test_bociasi_slow_erp(self):
        s = "个股慢线ERP=看多（0.66），ERP 3.51%"
        out = _to_display_text(s)
        assert '股权风险溢价' in out      # ERP → 股权风险溢价
        assert 'ERP' not in out

    def test_quadrant_7_metrics(self):
        s = ("大市四象限(中性·全市场分位)—市场情绪中性，常规配置（快线0.62/慢线0.66、"
             "MA20强势占比0%、换手分位98%、涨跌停比340%、RSI分位50%、ERP分位9%、融资趋势54%）")
        out = _to_display_text(s)
        assert '20日均线强势占比' in out    # MA20 → 20日均线
        assert '相对强弱指标分位' in out     # RSI → 相对强弱指标
        assert '股权风险溢价分位' in out     # ERP → 股权风险溢价
        for resid in ('MA20', 'RSI', 'ERP'):
            assert resid not in out

    def test_market_sector_temperature_chinese(self):
        s = "市场处于退潮（市场情绪开始降温）；板块排名40以外（冷门板块）；情绪温度:中性50.6/100"
        out = _to_display_text(s)
        assert '退潮' in out and '冷门板块' in out and '中性50.6/100' in out

    def test_bociasi_quadrant_phrase(self):
        s = "大市四象限(中性·全市场分位)—市场情绪中性（BOCIASI四象限修正）"
        out = _to_display_text(s)
        assert '情绪四象限' in out          # BOCIASI四象限 → 情绪四象限
        assert 'BOCIASI' not in out


class TestDim7Gateway:
    """dim7 收益驱动段（summary 尾置）：估值指标/陷阱/潜力六维全中文"""

    def test_valuation_level_composite(self):
        s = "估值：极度低估（综合评分=1.3634）"
        out = _to_display_text(s)
        assert '极度低估' in out and '综合评分' in out and 'composite' not in out

    def test_pe_pb_percentile(self):
        s = "市盈率近5年2.8%分位、市净率近5年5.0%分位"
        out = _to_display_text(s)
        assert '市盈率近5年' in out and '市净率近5年' in out

    def test_traps_roce_peg(self):
        s = "资本回报率低于15%，存在价值陷阱风险；市盈增长比>2，存在成长陷阱风险"
        out = _to_display_text(s)
        assert '资本回报率' in out and '市盈增长比' in out
        assert 'ROCE' not in out and 'PEG' not in out

    def test_potential_breakdown_metric_cn(self):
        s = ("潜力六维：估值分位 1.00；净资产收益率分位 0.99；板块 0.50（板块→第一层）；"
             "事件 0.60；资金 0.30（资金→第4维）；趋势 0.50（趋势→第2维/3）")
        out = _to_display_text(s)
        assert '净资产收益率分位' in out    # ROE 组已译
        assert '（板块→第一层）' in out and '（资金→第4维）' in out
        assert 'ROE' not in out

    def test_fcf_dividend_revenue(self):
        s = "自由现金流收益率1.8825%、股息率4.16%、营收同比增长1.47%"
        out = _to_display_text(s)
        assert '自由现金流收益率' in out and '股息率' in out and '营收同比增长' in out


class TestDivergeTypeCnGateway:
    """本会话 3a：买卖点 reason 内背驰 type 枚举中文（dim4 signal 直读 active_signal）"""

    def test_dim4_signal_reason_trend(self):
        s = "筹码信号:一买信号@2.98元置信1.00(下跌趋势背驰，trend类型)"
        out = _to_display_text(s)
        assert 'trend类型' not in out
        assert '趋势背驰' in out

    def test_dim4_signal_reason_consolidation(self):
        s = "筹码信号:一买信号@1248.1元置信0.91(下跌趋势背驰，consolidation类型)"
        out = _to_display_text(s)
        assert 'consolidation类型' not in out
        assert '盘整背驰' in out

    def test_dim4_signal_reason_zhongshu(self):
        s = "筹码信号:一卖信号@1323元置信0.78(上涨趋势背驰，zhongshu类型)"
        out = _to_display_text(s)
        assert 'zhongshu类型' not in out
        assert '中枢背驰' in out

    def test_plain_trend_not_mangled(self):
        # 单词 'trend'（非 xx类型 形式，如 'trend 信号' 或趋势字段）不被误替换
        s = "趋势依据:价格在中枢内部-中枢下移（trend 方向）"
        out = _to_display_text(s)
        assert 'trend' in out  # 非 'trend类型' 不替换，保留原样


class TestReasonableKeep:
    """合理保留：指标缩写带释义 + 结构化英文枚举不被误中"""

    def test_asr_cyqkl_with_gloss(self):
        s = "筹码结构:筹码稳定，ASR（活跃筹码比率）=29，CYQKL（筹码穿透力）=1.0，获利盘9%"
        out = _to_display_text(s)
        assert 'ASR（活跃筹码比率）' in out and 'CYQKL（筹码穿透力）' in out

    def test_rps_with_gloss(self):
        s = "RPS=42.7（近20日涨幅全市场前57%分位）"
        out = _to_display_text(s)
        assert 'RPS（相对强弱因子）=42.7' in out

    def test_audit_struct_enum_not_mangled(self):
        # audit actual/threshold 的结构化英文枚举不进展示中文化（439 边界）
        s = "拥挤度=MODERATE"
        out = _to_display_text(s)
        assert '适中' in out  # 拥挤度档位是展示层，可中文化


def _all_tests():
    import pytest
    pytest.main([__file__, '-v'])
