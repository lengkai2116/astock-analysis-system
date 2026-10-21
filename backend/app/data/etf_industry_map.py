"""ETF → 申万一级行业 / 主题映射（532号 批次1）

用途：板块热度五维 D2「ETF 份额变化」维度需要把 ETF 份额变化归到行业。
数据源：Tushare `fund_basic(market='E')`（名称 + 业绩比较基准）。
口径：
  - 行业 ETF：名称/基准命中申万一级行业名或行业关键词 → etf_type='industry'
  - 主题 ETF：命中主题词（人工智能/机器人/新能源车等）→ 映射到最接近的申万一级，
    etf_type='theme'（与行业 ETF 区分，避免污染行业口径）
  - 宽基/债券/商品/跨境 ETF：跳过（不做行业归属）

本模块仅由采集层（data_daemon / 回填脚本）调用；不读业务库、不做计算消费。
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta

import pandas as pd

logger = logging.getLogger(__name__)

TABLE = 'etf_industry_map'
_MIN_ROWS = 50
_DEFAULT_MAX_AGE_DAYS = 30

# 申万一级（SW2021）31 类
SW_INDUSTRIES = [
    '农林牧渔', '基础化工', '钢铁', '有色金属', '电子', '家用电器', '食品饮料',
    '纺织服饰', '轻工制造', '医药生物', '公用事业', '交通运输', '房地产',
    '商贸零售', '社会服务', '综合', '建筑材料', '建筑装饰', '电力设备',
    '国防军工', '计算机', '传媒', '通信', '银行', '非银金融', '汽车',
    '机械设备', '煤炭', '石油石化', '环保', '美容护理',
]

# 行业关键词（补充行业名之外的常见 ETF 命名）
INDUSTRY_KEYWORDS = {
    '电子': ['半导体', '芯片', '消费电子', '面板', '元器件', '集成电路', '光刻'],
    '电力设备': ['光伏', '储能', '电池', '锂电', '风电', '电网', '新能车', '电力设备'],
    '医药生物': ['医药', '医疗', '生物', '创新药', '疫苗', '中药', 'CXO'],
    '食品饮料': ['食品', '饮料', '白酒', '酒'],
    '有色金属': ['有色', '稀土', '黄金', '铜', '铝', '锂', '钴', '镍'],
    '基础化工': ['化工', '化学', '新材料', '氟化工', '磷化工'],
    '国防军工': ['军工', '国防', '航天', '航空', '卫星', '兵器'],
    '计算机': ['计算机', '软件', '信创', '云计算', '大数据', '网络安全', '数字经济'],
    '通信': ['通信', '5G', '光模块', '运营商'],
    '传媒': ['传媒', '游戏', '影视', '动漫', '出版'],
    '汽车': ['汽车', '整车', '汽车零部件'],
    '机械设备': ['机械', '工程机械', '机器人', '工业母机', '智能制造'],
    '银行': ['银行'],
    '非银金融': ['证券', '保险', '金融科技', '非银'],
    '房地产': ['房地产', '地产'],
    '建筑装饰': ['建筑', '基建', '工程'],
    '建筑材料': ['建材', '水泥', '玻璃'],
    '煤炭': ['煤炭', '焦煤'],
    '石油石化': ['石油', '石化', '油气', '能源化工'],
    '公用事业': ['电力', '公用事业', '燃气', '水务'],
    '交通运输': ['交通运输', '物流', '航运', '港口', '机场', '公路', '铁路'],
    '农林牧渔': ['农业', '养殖', '畜牧', '种业', '饲料', '渔业'],
    '环保': ['环保', '碳中和', '污水', '固废'],
    '美容护理': ['美容', '化妆品', '护理'],
    '商贸零售': ['商贸', '零售', '电商', '免税'],
    '社会服务': ['旅游', '酒店', '餐饮', '教育', '社会服务'],
    '纺织服饰': ['纺织', '服饰', '服装'],
    '轻工制造': ['轻工', '家居', '造纸', '包装'],
    '家用电器': ['家电', '家用电器'],
    '钢铁': ['钢铁', '特钢'],
}

# 主题词 → 最接近的申万一级（仅跨行业主题；行业子类走 INDUSTRY_KEYWORDS）
THEME_TO_SW = {
    '人工智能': '计算机',
    '机器人': '机械设备',
    '新能源汽车': '汽车',
    '新能源车': '汽车',
    '智能汽车': '汽车',
    '数字经济': '计算机',
    '云计算': '计算机',
    '大数据': '计算机',
    '信创': '计算机',
    '游戏': '传媒',
    '影视': '传媒',
    '卫星': '国防军工',
}

# 宽基/债券/商品/跨境：不做行业归属
BROAD_EXCLUDE = [
    '沪深300', '中证500', '中证1000', '中证2000', '中证A500', '上证50',
    '科创50', '科创100', '创业板', '深证100', '深证成指', '上证180',
    '全指', 'MSCI', '富时', '标普', '纳斯达克', '恒生', '港股', 'H股',
    '国债', '政金债', '信用债', '可转债', '货币', '黄金', '白银', '原油',
    '豆粕', '商品', 'QDII', '美元', '港币',
]


def _text(name, benchmark) -> str:
    return f"{name or ''} {benchmark or ''}"


def classify_etf(fund_name, benchmark):
    """返回 (sw_industry, etf_type) 或 (None, None)。

    优先级：宽基排除 → 主题词（长词优先）→ 行业名精确命中 → 行业关键词。
    主题先行，避免「新能源汽车」被行业名「汽车」抢先归为 industry。
    """
    text = _text(fund_name, benchmark)
    if not text.strip():
        return None, None
    if any(k in text for k in BROAD_EXCLUDE):
        return None, None

    # 1) 跨行业主题（长词优先）
    for theme in sorted(THEME_TO_SW, key=len, reverse=True):
        if theme in text:
            return THEME_TO_SW[theme], 'theme'

    # 2) 申万一级行业名直接命中
    for ind in SW_INDUSTRIES:
        if ind in text:
            return ind, 'industry'

    # 3) 行业关键词（长词优先）
    for ind, kws in INDUSTRY_KEYWORDS.items():
        for kw in sorted(kws, key=len, reverse=True):
            if kw in text:
                return ind, 'industry'
    return None, None


def build_etf_industry_rows(fund_df: pd.DataFrame) -> tuple[pd.DataFrame, dict]:
    """从 fund_basic 结果构建映射行；返回 (df, stats)。"""
    if fund_df is None or fund_df.empty:
        return pd.DataFrame(), {'total': 0, 'mapped': 0, 'industry': 0, 'theme': 0}

    now = datetime.now().isoformat(timespec='seconds')
    rows = []
    total = 0
    for _, r in fund_df.iterrows():
        name = str(r.get('name') or '')
        ft = str(r.get('fund_type') or '')
        if 'ETF' not in name and 'ETF' not in ft:
            continue
        total += 1
        ind, etype = classify_etf(name, r.get('benchmark'))
        if not ind:
            continue
        rows.append({
            'ts_code': str(r.get('ts_code') or ''),
            'fund_name': name,
            'benchmark': str(r.get('benchmark') or ''),
            'sw_industry': ind,
            'etf_type': etype,
            'mapping_source': 'rule',
            'updated_at': now,
        })
    df = pd.DataFrame(rows)
    stats = {
        'total': total,
        'mapped': len(df),
        'industry': int((df['etf_type'] == 'industry').sum()) if len(df) else 0,
        'theme': int((df['etf_type'] == 'theme').sum()) if len(df) else 0,
    }
    return df, stats


def _ecm(ecm=None):
    if ecm is not None:
        return ecm
    from app.data import get_ecm_instance
    return get_ecm_instance()


def get_etf_industry_status(ecm=None) -> tuple[int, str | None]:
    ecm = _ecm(ecm)
    try:
        df = ecm._query_shard(TABLE, "SELECT COUNT(*) AS n, MAX(updated_at) AS ts FROM " + TABLE)
        if df is None or df.empty:
            return 0, None
        n = int(df['n'].iloc[0] or 0)
        ts = df['ts'].iloc[0]
        return n, (str(ts) if ts else None)
    except Exception:
        return 0, None


def refresh_etf_industry_map(ecm=None, force: bool = False,
                             max_age_days: int = _DEFAULT_MAX_AGE_DAYS) -> int:
    """刷新 ETF→行业映射，返回映射行数；未过期/失败保留旧表。"""
    ecm = _ecm(ecm)
    if not force:
        n, ts = get_etf_industry_status(ecm)
        if n >= _MIN_ROWS and ts:
            try:
                if datetime.now() - datetime.fromisoformat(ts) < timedelta(days=max_age_days):
                    return n
            except Exception:
                pass

    try:
        from app.data.tushare_provider import TushareProvider
        provider = TushareProvider()
        fund_df = provider.get_fund_basic(market='E')
        if fund_df is None or fund_df.empty:
            logger.warning("ETF行业映射: fund_basic 返回空，保留旧表")
            return get_etf_industry_status(ecm)[0]

        df, stats = build_etf_industry_rows(fund_df)
        if len(df) < _MIN_ROWS:
            logger.warning(f"ETF行业映射: 映射行数不足（{len(df)} < {_MIN_ROWS}），保留旧表")
            return get_etf_industry_status(ecm)[0]

        n = ecm.cache_etf_industry_map(df)
        if n:
            coverage = stats['mapped'] / stats['total'] * 100 if stats['total'] else 0
            logger.info(
                f"ETF行业映射刷新: {n} 条（行业 {stats['industry']} / 主题 {stats['theme']}，"
                f"覆盖 {coverage:.1f}%）")
        return n
    except Exception as e:
        logger.warning(f"ETF行业映射刷新失败，保留旧表: {e}")
        return get_etf_industry_status(ecm)[0]
