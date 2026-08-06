"""
Advice Generator — 操作建议生成器

从 P1.2 标的库 + P2.2 L4 诊断输出 → 自动生成操作建议并写入 opportunity_library。
"""

import json
import logging
from datetime import datetime

from app.data.mixins import DataAwareMixin

logger = logging.getLogger(__name__)


class AdviceGenerator(DataAwareMixin):
    """操作建议生成器"""

    def __init__(self):
        self._dm = None  # DataAwareMixin 统一注入点
        self._l4 = None

    @property
    def l4(self):
        if self._l4 is None:
            from app.opportunity_atlas.cross_validate import L4CrossValidator
            self._l4 = L4CrossValidator()
        return self._l4

    # ══════════════════════════════════════════════════════════
    # 主入口
    # ══════════════════════════════════════════════════════════

    def generate_advice(self, ts_code: str, tags: dict = None) -> dict:
        """生成单只股票的操作建议

        Args:
            ts_code: 股票代码
            tags: 可选预加载标签（None 则从 ECM 读取）

        Returns:
            action / label / max_position_ratio / entry_plan / stop_loss /
            target_price / reason / generated_at
        """
        try:
            return self._generate_from_l4(ts_code, tags)
        except Exception as e:
            logger.warning('L4 diagnose failed for %s: %s, fallback', ts_code, e)
            return self._generate_fallback(ts_code, tags)

    def _generate_from_l4(self, ts_code: str, tags: dict = None) -> dict:
        """通过 L4 诊断生成操作建议"""
        diagnosis = self.l4.diagnose(ts_code, tags)
        op_advice = diagnosis.get('operation_advice', {})
        cross = diagnosis.get('cross_validation', {})
        tags_summary = diagnosis.get('tags_summary', {})

        action = op_advice.get('action', 'hold')
        label = op_advice.get('label', '持有')
        max_position_ratio = op_advice.get('max_position_ratio', 0.0)
        entry_plan = op_advice.get('entry_plan', [])
        stop_loss = op_advice.get('stop_loss')
        target_price = op_advice.get('target_price')

        # 构建综合理由
        reason_parts = []
        verdict = cross.get('verdict', '')
        if verdict:
            reason_parts.append(verdict)
        for key, name in [('direction', '方向'), ('position', '位置'), ('quality', '质量')]:
            val = tags_summary.get(key, '')
            if val:
                reason_parts.append(f'{name}: {val}')
        reason = '；'.join(reason_parts)

        # 提取 signal_strength_adjusted（优先）或原值
        signal_strength = diagnosis.get('signal_strength_adjusted', 0)
        if not signal_strength and tags:
            signal_strength = float(tags.get('signal_strength', 0))

        self._update_library(ts_code, action, label, max_position_ratio,
                             entry_plan, stop_loss, target_price, reason, signal_strength)

        return {
            'action': action,
            'label': label,
            'max_position_ratio': max_position_ratio,
            'entry_plan': entry_plan,
            'stop_loss': stop_loss,
            'target_price': target_price,
            'reason': reason,
            'generated_at': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
        }

    def _generate_fallback(self, ts_code: str, tags: dict = None) -> dict:
        """L4 不可用时使用简化规则回退"""
        signal_strength = float(tags.get('signal_strength', 0)) if tags else 0

        # 313号：signal_strength 0-100 潜力强度（旧 0-10 的 ×10 迁移）
        if signal_strength >= 70:
            action, label, max_ratio = 'build_position', '建仓', 0.6
        elif signal_strength >= 50:
            action, label, max_ratio = 'hold', '持有观察', 0.3
        elif signal_strength >= 30:
            action, label, max_ratio = 'reduce', '减仓', 0.1
        else:
            action, label, max_ratio = 'clear', '清仓', 0.0

        entry_plan = []
        if action == 'build_position':
            entry_plan = [
                {'price': '当前价', 'ratio': '60%', 'condition': '首次建仓'},
                {'price': '回踩确认', 'ratio': '40%', 'condition': '分批加仓'},
            ]

        reason = f'简化规则：signal_strength={signal_strength} → {label}（L4不可用）'

        self._update_library(ts_code, action, label, max_ratio,
                             entry_plan, None, None, reason, signal_strength)

        return {
            'action': action,
            'label': label,
            'max_position_ratio': max_ratio,
            'entry_plan': entry_plan,
            'stop_loss': None,
            'target_price': None,
            'reason': reason,
            'generated_at': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
        }

    def _update_library(self, ts_code: str, action: str, label: str,
                        max_position_ratio: float, entry_plan: list,
                        stop_loss: float | None, target_price: float | None,
                        reason: str, signal_strength: float) -> None:
        """写入操作建议到 opportunity_library"""
        from app import db

        lib = self._get_dm().get_library_entry(ts_code)
        if lib is None:
            logger.warning('AdviceGenerator: 标的 %s 不在机会库中，跳过写入', ts_code)
            return

        advice = {
            'action': action,
            'label': label,
            'max_position_ratio': max_position_ratio,
            'entry_plan': entry_plan,
            'stop_loss': stop_loss,
            'target_price': target_price,
            'reason': reason,
        }
        lib.operation_advice = json.dumps(advice, ensure_ascii=False)
        lib.total_score = signal_strength
        lib.last_update = datetime.now().strftime('%Y-%m-%d %H:%M')
        db.session.commit()

    # ══════════════════════════════════════════════════════════
    # 批量更新
    # ══════════════════════════════════════════════════════════

    def batch_update_library(self, ts_codes: list[str] = None) -> int:
        """批量更新标的库中所有股票的操作建议

        从 opportunity_library 读取 active 股票，逐个运行诊断后写回。
        单只股票失败不影响其他股票。

        Args:
            ts_codes: 要更新的股票列表（None 则更新所有 active 标的）

        Returns:
            成功更新的股票数量
        """
        from app import db

        stocks = self._get_dm().get_library_active_items()
        if ts_codes:
            stocks = [s for s in stocks if s.ts_code in ts_codes]
        if not stocks:
            logger.info('AdviceGenerator: 没有 active 标的需要更新')
            return 0

        success = 0
        for stock in stocks:
            try:
                self.generate_advice(stock.ts_code)
                # 自动升级：scan→watch（signal_strength > 6.0 持续3日 + phase_confidence > 0.6）
                self._auto_upgrade_scan(stock)
                success += 1
            except Exception as e:
                logger.error('AdviceGenerator: %s 更新失败: %s', stock.ts_code, e)

        logger.info('AdviceGenerator: 批量更新完成，成功 %d/%d', success, len(stocks))
        return success

    def _auto_upgrade_scan(self, stock) -> None:
        """scan 自动升级 watch（299号§二 等级流转规则）"""
        if stock.lib_level != 'scan':
            return
        try:
            tags = self._get_dm().cache.get_tags(stock.ts_code)
            if not tags:
                return
            ss = float(tags.get('signal_strength', 0) or 0)
            pc = float(tags.get('phase_confidence', 0) or 0)
            if ss > 6.0 and pc > 0.6:
                stock.lib_level = 'watch'
                stock.last_update = datetime.now().strftime('%Y-%m-%d %H:%M')
                from app import db
                db.session.commit()
                logger.info('  scan→watch 自动升级: %s (signal=%.1f, conf=%.2f)',
                            stock.ts_code, ss, pc)
        except Exception:
            pass
