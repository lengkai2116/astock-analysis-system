"""
P2.4 机会雷达 + 自选看板 + 通知推送
==================================
三层只读服务：
  - 机会雷达：非自选股中信号强度最高的股票
  - 自选看板：自选库聚合（标签 + 统计 + 诊断）
  - 通知推送：基于标签状态的推送分级评估
"""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Any

from app.data.mixins import DataAwareMixin

logger = logging.getLogger(__name__)


class RadarService(DataAwareMixin):
    """机会雷达、自选看板聚合、通知推送服务"""

    def __init__(self, data_manager=None):
        self._dm = data_manager  # DataAwareMixin 统一注入点
        self._ecm = None

    def _get_ecm(self):
        """缓存友好的 ECM 访问（减少重复链式调用）"""
        if self._ecm is None:
            self._ecm = self._get_cache()
        return self._ecm

    def _get_stock_name(self, ts_code: str) -> str:
        try:
            info = self._get_dm().get_stock_info(ts_code)
            return info.get('name', '') if info else ''
        except Exception:
            return ''

    # ══════════════════════════════════════════════════════
    # 机会雷达
    # ══════════════════════════════════════════════════════

    def get_radar_signals(self, limit: int = 20) -> list[dict]:
        """机会雷达：非自选股中信号强度最高的股票

        逻辑：
        1. 从 opportunity_tags_cache 读取所有有标签的股票
        2. 排除已在 opportunity_library 中的（自选股）
        3. 按 signal_strength 降序排列取 top N
        4. 对每只雷达股展示关键标签
        """
        cache = self._get_dm().cache

        # 1. 获取所有有标签的 ts_code
        try:
            df = cache._query_df(
                "SELECT DISTINCT ts_code FROM opportunity_tags_cache"
            )
            all_tagged = df["ts_code"].tolist()
        except Exception as e:
            logger.warning("get_radar_signals: 查询标签表失败: %s", e)
            return []
        if not all_tagged:
            return []

        # 2. 排除自选库中的股票
        try:
            library_codes = set(self._get_dm().get_library_ts_codes())
        except Exception as e:
            logger.warning("get_radar_signals: 查询机会库失败: %s", e)
            library_codes = set()

        candidates = [c for c in all_tagged if c not in library_codes]
        if not candidates:
            return []

        # 3. 批量获取标签（最多取 200 只候选避免过大开销）
        batch = cache.get_tags_batch(candidates[:200])

        # 4. 按 signal_strength 降序排列
        scored: list[dict] = []
        for ts_code, tags in batch.items():
            scored.append({
                'ts_code': ts_code,
                'name': self._get_stock_name(ts_code),
                'signal_strength': self._safe_float(tags.get('signal_strength'), 0),
                'main_force_phase': tags.get('main_force_phase', ''),
                'catalyst_event': tags.get('catalyst_event', ''),
                'valuation_level': tags.get('valuation_level', ''),
                'sector_heat': tags.get('sector_heat', ''),
            })

        scored.sort(key=lambda x: x['signal_strength'], reverse=True)
        return scored[:limit]

    # ══════════════════════════════════════════════════════
    # 自选看板
    # ══════════════════════════════════════════════════════

    def get_watchboard(self, ts_codes: list[str] = None) -> dict:
        """自选看板聚合接口

        Args:
            ts_codes: 股票列表，None 时从 opportunity_library 读取活跃自选

        Returns:
            { stocks: [...], dashboard: { total_count, building_count,
              alert_count, high_signal_count }, generated_at }
        """
        if ts_codes is None:
            try:
                ts_codes = self._get_dm().get_library_ts_codes(active_only=True)
            except Exception as e:
                logger.warning("get_watchboard: 查询机会库失败: %s", e)
                now = datetime.now().isoformat()
                return {'stocks': [], 'dashboard': self._empty_stats(),
                        'generated_at': now}

        if not ts_codes:
            now = datetime.now().isoformat()
            return {'stocks': [], 'dashboard': self._empty_stats(),
                    'generated_at': now}

        # 批量获取标签和名称
        ecm = self._get_ecm()
        batch_tags = ecm.get_tags_batch(ts_codes)
        name_map = {tc: self._get_stock_name(tc) for tc in ts_codes}

        stats = {'total_count': len(ts_codes), 'building_count': 0,
                 'alert_count': 0, 'high_signal_count': 0}
        stocks: list[dict] = []

        for ts_code in ts_codes:
            tags = batch_tags.get(ts_code, {})

            # 看板统计
            if tags.get('main_force_phase') == 'building':
                stats['building_count'] += 1
            ss = self._safe_float(tags.get('signal_strength'), 0)
            if ss >= 7:
                stats['high_signal_count'] += 1
            if tags.get('fina_health') in ('suspicious', 'fail'):
                stats['alert_count'] += 1

            stocks.append({
                'ts_code': ts_code,
                'name': name_map.get(ts_code, ''),
                'tags': tags,
            })

        return {
            'stocks': stocks,
            'dashboard': stats,
            'generated_at': datetime.now().isoformat(),
        }

    # ══════════════════════════════════════════════════════
    # 通知推送
    # ══════════════════════════════════════════════════════

    def get_notifications(self) -> list[dict]:
        """通知评估：基于 L4 daily_change_summary 产出推送

        推送分级（299号§5.3，基于变化diff而非快照）：
          - urgent:   fina_health→fail 或 valuation_level→extreme_high
          - important: main_force_phase 切换 或 catalyst_event 有值
          - normal:    signal_strength ±1.0 或 trend_alignment 反转

        返回按优先级降序排列：urgent > important > normal
        """
        l4 = self._get_l4()
        notifications: list[dict] = []

        try:
            lib_items = self._get_dm().get_library_active_items()
        except Exception as e:
            logger.warning("get_notifications: 查询机会库失败: %s", e)
            return []

        for item in lib_items:
            try:
                diagnosis = l4.diagnose(item.ts_code)
            except Exception as e:
                logger.warning("get_notifications: 诊断 %s 失败: %s",
                               item.ts_code, e)
                continue

            daily_change = diagnosis.get('cross_validation', {}).get(
                'daily_change_summary', {})
            level, title, message = self._evaluate_push_level(item, daily_change)
            if level is None:
                continue

            notifications.append({
                'ts_code': item.ts_code,
                'name': item.name or self._get_stock_name(item.ts_code),
                'level': level,
                'title': title,
                'message': message,
                'category': 'opportunity',
                'generated_at': datetime.now().isoformat(),
            })

        # urgent(0) -> important(1) -> normal(2)
        priority = {'urgent': 0, 'important': 1, 'normal': 2}
        notifications.sort(key=lambda n: priority.get(n['level'], 3))
        return notifications

    # ── 推送级别评估 ──────────────────────────────────────

    @staticmethod
    def _get_l4():
        """延迟导入 L4CrossValidator"""
        from app.opportunity_atlas.cross_validate import L4CrossValidator
        return L4CrossValidator()

    @staticmethod
    def _evaluate_push_level(item: Any, daily_change: dict
                             ) -> tuple[str | None, str, str]:
        """基于 daily_change_summary 评估推送级别

        Returns:
            (level, title, message) 或 (None, '', '') 表示无需推送
        """
        if not daily_change.get('has_changes'):
            return (None, '', '')

        changes = daily_change.get('changes', [])
        if not changes:
            return (None, '', '')

        # 按严重度排序
        level_order = {'urgent': 0, 'important': 1, 'normal': 2}
        top_level = 'normal'
        top_summaries = []

        for c in changes:
            cl = c.get('level', 'normal')
            summary = c.get('summary', '')
            if level_order.get(cl, 99) < level_order.get(top_level, 99):
                top_level = cl
            if summary:
                top_summaries.append(summary)

        ts_code = item.ts_code
        top_summary = top_summaries[0] if top_summaries else ''

        if top_level == 'urgent':
            return ('urgent',
                    '\u26a0 ' + ts_code + ' \u91cd\u8981\u53d8\u5316',
                    '\u53d1\u73b0\u7d27\u6025\u53d8\u5316: ' + '; '.join(
                        s for s in top_summaries[:3]))
        elif top_level == 'important':
            return ('important',
                    '\u25c6 ' + ts_code + ' \u4fe1\u53f7\u53d8\u5316',
                    '\u53d1\u73b0\u91cd\u8981\u53d8\u5316: ' + '; '.join(
                        s for s in top_summaries[:3]))
        else:
            return ('normal',
                    '\u2606 ' + ts_code + ' \u6807\u7b7e\u53d8\u5316',
                    '; '.join(top_summaries[:3]))

    # ── 辅助方法 ──────────────────────────────────────────

    @staticmethod
    def _empty_stats() -> dict:
        return {'total_count': 0, 'building_count': 0,
                'alert_count': 0, 'high_signal_count': 0}

    @staticmethod
    def _safe_float(v: Any, default: float = 0) -> float:
        try:
            return float(v) if v is not None else default
        except (ValueError, TypeError):
            return default
