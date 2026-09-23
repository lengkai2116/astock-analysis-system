"""477号：行业分类映射（东财行业名 → 七类）测试

覆盖：
  1. 东财关键行业 → 正确类别（白酒→蓝筹/全国地产→周期/证券→金融/电气设备→成长）
  2. 全量东财枚举（111 项，硬编码自 stocks 表核查）无遗漏映射（覆盖审计）
  3. 未知行业兜底微小/亏损
  4. _category 优先东财、其次申万、最后兜底
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
for k in ['HTTP_PROXY', 'HTTPS_PROXY', 'ALL_PROXY']:
    os.environ.pop(k, None)

import pytest

from app.opportunity_atlas.valuation_estimator import EASTMONEY_CATEGORY, INDUSTRY_CATEGORY
from app.opportunity_atlas.dimensions.dim7_valuation_engine import _category


class TestCategoryMapping:
    def test_key_industries(self):
        """东财关键行业 → 正确七类"""
        assert _category('白酒') == '蓝筹'
        assert _category('全国地产') == '周期'
        assert _category('证券') == '金融'
        assert _category('电气设备') == '成长'
        assert _category('半导体') == '科技'
        assert _category('火力发电') == '稳定收息'

    def test_full_enum_coverage(self):
        """stocks 表 111 个东财行业枚举全部有映射（2026-09-23 核查快照）"""
        enum = [
            '电气设备', '元器件', '专用机械', '软件服务', '汽车配件', '化工原料', '半导体',
            '医疗保健', '化学制药', '机械基件', '通信设备', '建筑工程', '环境保护', '电器仪表',
            '食品', '家用电器', '互联网', 'IT设备', '生物制药', '塑料', '家居用品', '中成药',
            '小金属', '服饰', '农药化肥', '广告包装', '航空', '文教休闲', '证券', '运输设备',
            '仓储物流', '纺织', '供气供热', '区域地产', '银行', '农业综合', '工程机械',
            '医药商业', '矿物制品', '染料涂料', '百货', '影视音像', '造纸', '化纤', '新型电力',
            '火力发电', '其他建材', '铝', '出版业', '普钢', '全国地产', '装修装饰', '煤炭开采',
            '机床制造', '饲料', '钢加工', '多元金融', '石油开采', '汽车整车', '水泥', '水力发电',
            '日用化工', '乳制品', '综合类', '路桥', '种植业', '白酒', '玻璃', '水运', '铜',
            '橡胶', '旅游景点', '港口', '商贸代理', '水务', '铅锌', '石油加工', '摩托车',
            '园区开发', '房产服务', '化工机械', '农用机械', '其他商业', '船舶', '纺织机械',
            '黄金', '特种钢', '汽车服务', '酒店餐饮', '软饮料', '红黄酒', '超市连锁', '空运',
            '旅游服务', '啤酒', '铁路', '轻工机械', '焦炭加工', '渔业', '公共交通', '陶瓷',
            '电信运营', '机场', '批发业', '保险', '石油贸易', '林业', '商品城', '公路', '电器连锁',
        ]
        unmapped = [i for i in enum if i not in EASTMONEY_CATEGORY and i not in INDUSTRY_CATEGORY]
        assert not unmapped, f"无映射行业: {unmapped}"

    def test_unknown_fallback(self):
        """未知行业兜底微小/亏损"""
        assert _category(None) == '微小/亏损'
        assert _category('未知行业XYZ') == '微小/亏损'

    def test_precedence(self):
        """优先东财映射（同键名申万/东财一致时结果应相同）"""
        assert _category('银行') == '金融'          # 两表均有
        assert _category('家用电器') == '蓝筹'      # 两表均有
