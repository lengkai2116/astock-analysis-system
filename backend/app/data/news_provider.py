"""
NewsProvider — 消息面上下文数据源
==================================
实现 153-P1-3: 新闻/公告数据源抽象层

支持:
- Tushare News API (news / major_news)
- AKShare 财经新闻备用
- 本地 Mock 数据（无 API 时可运行）
"""

import logging
import random
from typing import List, Optional, Dict
from datetime import datetime, timedelta

logger = logging.getLogger(__name__)


class NewsItem:
    """单条新闻"""
    def __init__(self, title: str, content: str = "", source: str = "",
                 date: str = "", sentiment: float = 0.0,
                 impact: str = "neutral", url: str = ""):
        self.title = title
        self.content = content
        self.source = source
        self.date = date
        self.sentiment = sentiment   # -1.0 ~ 1.0
        self.impact = impact         # 'positive' / 'negative' / 'neutral'
        self.url = url

    def to_dict(self) -> Dict:
        return {
            'title': self.title,
            'content': self.content[:200],
            'source': self.source,
            'date': self.date,
            'sentiment': self.sentiment,
            'impact': self.impact,
            'url': self.url,
        }

    def to_context(self) -> str:
        return f"[{self.date}] {self.title} (来源:{self.source}, 情绪:{self.impact})"


class NewsProvider:
    """
    消息面数据提供者

    使用方式:
        provider = NewsProvider()
        news = provider.get_news('000001.SZ', days_back=7)
    """

    def __init__(self):
        self._tushare_available = self._check_tushare()

    def _check_tushare(self) -> bool:
        try:
            import tushare as ts
            token = __import__('app.config', fromlist=['Config']).Config.TUSHARE_TOKEN
            if token:
                ts.set_token(token)
                pro = ts.pro_api()
                # 测试新闻接口
                df = pro.news(src='sina', start_date='20250101', limit=1)
                return df is not None
        except Exception:
            pass
        return False

    def get_news(self, ts_code: str, days_back: int = 7,
                 max_count: int = 10) -> List[NewsItem]:
        """
        获取指定股票的新闻

        Args:
            ts_code: 股票代码
            days_back: 回溯天数
            max_count: 最大返回条数

        Returns:
            NewsItem 列表
        """
        if self._tushare_available:
            try:
                return self._fetch_tushare(ts_code, days_back, max_count)
            except Exception as e:
                logger.warning(f"Tushare 新闻获取失败: {e}")

        return self._fetch_mock(ts_code, max_count)

    def get_market_news(self, days_back: int = 1, max_count: int = 5) -> List[NewsItem]:
        """获取大盘/市场新闻"""
        if self._tushare_available:
            try:
                import tushare as ts
                pro = ts.pro_api()
                df = pro.news(src='sina', start_date=(datetime.now() - timedelta(days=days_back)).strftime('%Y%m%d'))
                if df is not None and not df.empty:
                    items = []
                    for _, row in df.head(max_count).iterrows():
                        items.append(NewsItem(
                            title=str(row.get('title', '')),
                            content=str(row.get('content', '')),
                            source='sina',
                            date=str(row.get('datetime', ''))[:10],
                            sentiment=0,
                            impact='neutral',
                        ))
                    return items
            except Exception:
                pass
        return self._fetch_mock('market', max_count)

    def _fetch_tushare(self, ts_code: str, days_back: int, max_count: int) -> List[NewsItem]:
        """从 Tushare 获取新闻"""
        import tushare as ts
        pro = ts.pro_api()
        start = (datetime.now() - timedelta(days=days_back)).strftime('%Y%m%d')

        items = []
        for src in ['sina', 'eastmoney']:
            try:
                df = pro.news(src=src, start_date=start)
                if df is not None and not df.empty:
                    for _, row in df.head(max_count).iterrows():
                        items.append(NewsItem(
                            title=str(row.get('title', '')),
                            content=str(row.get('content', '')),
                            source=src,
                            date=str(row.get('datetime', ''))[:10],
                            sentiment=0,
                            impact='neutral',
                        ))
            except Exception:
                continue
            if len(items) >= max_count:
                break
        return items[:max_count]

    def _fetch_mock(self, ts_code: str, max_count: int) -> List[NewsItem]:
        """Mock 数据（无 API 时使用）"""
        mock_topics = [
            ("板块资金流向追踪", "北向资金连续3日净流入", "positive"),
            ("成交量分析", "该股成交量温和放大", "positive"),
            ("技术形态评估", "短期均线多头排列", "positive"),
            ("市场情绪观察", "市场整体情绪偏谨慎", "neutral"),
            ("行业政策解读", "相关行业政策利好频出", "positive"),
            ("主力资金监测", "主力资金净流入明显", "positive"),
            ("公告解读", "公司发布业绩预增公告", "positive"),
            ("龙虎榜分析", "机构席位买入为主", "positive"),
            ("行业对比评估", "该股在行业中估值偏低", "neutral"),
            ("市场风险提示", "外围市场波动加剧", "negative"),
            ("资金流出预警", "大单资金持续流出", "negative"),
            ("技术指标预警", "MACD死叉信号出现", "negative"),
        ]
        random.seed(hash(ts_code) % (2**31))
        selected = random.sample(mock_topics, min(max_count, len(mock_topics)))
        result = []
        for title, content, impact in selected:
            days_ago = random.randint(0, 7)
            date = (datetime.now() - timedelta(days=days_ago)).strftime('%Y-%m-%d')
            sent = 0.3 if impact == 'positive' else (-0.3 if impact == 'negative' else 0)
            result.append(NewsItem(
                title=title, content=content, source='ai_mock',
                date=date, sentiment=sent, impact=impact,
            ))
        return result

    def build_context_section(self, news_list: List[NewsItem]) -> str:
        """构建 AI 提示上下文段"""
        if not news_list:
            return "近期无明显相关新闻。"
        lines = ["近期相关新闻/公告："]
        for n in news_list:
            lines.append(f"- {n.to_context()}")
        return "\n".join(lines)
