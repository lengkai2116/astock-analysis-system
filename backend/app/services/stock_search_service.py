"""
股票搜索服务

对照 151-观潮对标-系统能力提升与稳定性优化方案.md §3.2
支持股票代码精确匹配 / 名称模糊查询 / 拼音前缀搜索
"""

import re
import logging
from typing import List, Dict, Optional
from pypinyin import pinyin, Style

from app import db
from app.models import Stock

logger = logging.getLogger(__name__)


class StockSearchService:
    """股票搜索服务"""

    def __init__(self):
        self._pinyin_index: Dict[str, List[str]] = {}  # 拼音前缀 → [ts_code]
        self._index_built = False
        self._cache: Dict[str, List[Dict]] = {}
        self._cache_size = 50

    # ==================== 构建索引 ====================

    def rebuild_index(self):
        """重建拼音前缀索引"""
        self._pinyin_index.clear()
        self._cache.clear()

        try:
            stocks = Stock.query.all()
            for stock in stocks:
                name = stock.name or ''
                ts_code = stock.ts_code

                if not name:
                    continue

                # 首字母拼音
                try:
                    initials = ''.join(
                        p[0][0] for p in pinyin(name, style=Style.FIRST_LETTER)
                    )
                    self._add_to_index(initials, ts_code)
                except Exception:
                    pass

                # 全拼
                try:
                    full_pinyin = ''.join(
                        p[0] for p in pinyin(name, style=Style.TONE2)
                    )
                    self._add_to_index(full_pinyin, ts_code)
                except Exception:
                    pass

            self._index_built = True
            logger.info(f"拼音索引重建完成: {len(self._pinyin_index)} 前缀, {len(stocks)} 股票")
        except Exception as e:
            logger.error(f"拼音索引重建失败: {e}")

    def _add_to_index(self, key: str, ts_code: str):
        """添加到索引（只存前 3 个字符作为前缀）"""
        key = key.lower()
        # 存储所有前缀
        for i in range(1, min(len(key), 10) + 1):
            prefix = key[:i]
            if prefix not in self._pinyin_index:
                self._pinyin_index[prefix] = []
            if ts_code not in self._pinyin_index[prefix]:
                self._pinyin_index[prefix].append(ts_code)

    # ==================== 搜索 ====================

    def search(self, query: str, limit: int = 20) -> List[Dict]:
        """
        搜索股票

        优先级：
        1. 股票代码精确匹配
        2. 股票代码前缀匹配
        3. 拼音首字母匹配
        4. 名称模糊匹配

        Args:
            query: 搜索关键词
            limit: 返回条数上限

        Returns:
            [{ts_code, symbol, name, industry, market, match_type}]
        """
        if not query or not query.strip():
            return self._get_all(limit)

        query = query.strip()
        cache_key = f"{query}:{limit}"

        # 缓存命中
        if cache_key in self._cache:
            return self._cache[cache_key]

        results = []
        seen = set()

        # 1. 代码精确匹配
        exact = self._exact_code(query)
        for item in exact:
            if item['ts_code'] not in seen:
                seen.add(item['ts_code'])
                item['match_type'] = 'code_exact'
                results.append(item)

        if len(results) >= limit:
            return self._cache_result(cache_key, results[:limit])

        # 2. 代码前缀匹配
        code_prefix = self._code_prefix(query)
        for item in code_prefix:
            if item['ts_code'] not in seen and len(results) < limit:
                seen.add(item['ts_code'])
                item['match_type'] = 'code_prefix'
                results.append(item)

        if len(results) >= limit:
            return self._cache_result(cache_key, results[:limit])

        # 3. 拼音匹配
        pinyin_results = self._pinyin_search(query)
        for item in pinyin_results:
            if item['ts_code'] not in seen and len(results) < limit:
                seen.add(item['ts_code'])
                item['match_type'] = 'pinyin'
                results.append(item)

        if len(results) >= limit:
            return self._cache_result(cache_key, results[:limit])

        # 4. 名称模糊匹配
        name_fuzzy = self._name_fuzzy(query)
        for item in name_fuzzy:
            if item['ts_code'] not in seen and len(results) < limit:
                seen.add(item['ts_code'])
                item['match_type'] = 'name_fuzzy'
                results.append(item)

        return self._cache_result(cache_key, results[:limit])

    # ==================== 内部搜索方法 ====================

    def _exact_code(self, query: str) -> List[Dict]:
        """精确代码搜索"""
        stock = Stock.query.get(query)
        if stock:
            return [self._stock_to_dict(stock)]
        return []

    def _code_prefix(self, query: str) -> List[Dict]:
        """代码前缀匹配"""
        if not query.isdigit():
            return []
        stocks = Stock.query.filter(
            Stock.ts_code.startswith(query)
        ).limit(10).all()
        return [self._stock_to_dict(s) for s in stocks]

    def _pinyin_search(self, query: str) -> List[Dict]:
        """拼音前缀搜索"""
        if not self._index_built:
            self.rebuild_index()

        key = query.lower()
        ts_codes = self._pinyin_index.get(key, [])[:10]

        results = []
        for ts_code in ts_codes:
            stock = Stock.query.get(ts_code)
            if stock:
                results.append(self._stock_to_dict(stock))

        return results

    def _name_fuzzy(self, query: str) -> List[Dict]:
        """名称模糊搜索"""
        try:
            stocks = Stock.query.filter(
                Stock.name.ilike(f'%{query}%')
            ).limit(10).all()
            return [self._stock_to_dict(s) for s in stocks]
        except Exception:
            return []

    def _get_all(self, limit: int) -> List[Dict]:
        """获取全部股票（限制数量）"""
        try:
            stocks = Stock.query.order_by(Stock.ts_code).limit(limit).all()
            return [self._stock_to_dict(s) for s in stocks]
        except Exception:
            return []

    # ==================== 工具方法 ====================

    def _stock_to_dict(self, stock) -> Dict:
        return {
            'ts_code': stock.ts_code,
            'symbol': stock.symbol,
            'name': stock.name,
            'industry': stock.industry,
            'market': stock.market,
            'list_date': str(stock.list_date) if stock.list_date else None,
        }

    def _cache_result(self, key: str, result: List[Dict]) -> List[Dict]:
        """缓存搜索结果"""
        if len(self._cache) >= self._cache_size:
            # 移除最早缓存的 key
            oldest = next(iter(self._cache))
            del self._cache[oldest]
        self._cache[key] = result
        return result

    def clear_cache(self):
        """清除搜索缓存"""
        self._cache.clear()

    def get_search_suggestions(self, query: str, limit: int = 8) -> List[str]:
        """获取搜索建议（仅返回名称列表用于自动补全）"""
        results = self.search(query, limit)
        return [f"{r['ts_code']} {r['name']}" for r in results]


# 全局单例
stock_search_service = StockSearchService()
