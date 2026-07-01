"""
规则冷却/去重/确认期管理器 — RuleDeduplicator

控制通知触发的频率和质量：
  1. 冷却期 (Cooldown): 同一规则在 N 分钟内不重复推送
  2. 高频合并 (High-Frequency Merge): 极短时间内多次触发合并为一条通知
  3. 确认期 (Confirmation Period): 条件需连续 N 次评估均通过才正式推送

策略：
  - 默认冷却期: 60 分钟（用户可在规则配置中覆盖）
  - 高频合并窗口: 5 分钟内同一规则的多次触发 → 合并为单条通知
  - 确认期: 条件连续 3 次评估通过（每 5 分钟一次）后才推送
"""
import logging
from datetime import datetime, timedelta
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Any

logger = logging.getLogger(__name__)


@dataclass
class DedupResult:
    """冷却/去重/确认期检查结果"""
    should_dedup: bool = False       # 是否应去重（冷却期内）
    should_merge: bool = False       # 是否应合并到上一条通知
    should_delay: bool = False       # 是否应延迟推送（确认期内）
    master_notif_id: str = ''        # 合并的目标通知 ID
    reason: str = ''
    interim_count: int = 0           # 确认期中间计数
    confirmation_required: int = 0   # 需要的确认次数
    confirmation_achieved: int = 0   # 已达成的确认次数


# 内存状态 —— 用于冷却期和确认期追踪
_cooldown_state: Dict[str, datetime] = {}       # rule_id → 上次推送时间
_interim_state: Dict[str, int] = {}             # rule_id → 连续通过计数
_confirmation_settings: Dict[str, int] = {}     # rule_id → 所需确认次数
_merge_window_state: Dict[str, int] = {}        # rule_id → 上次合并通知的 notif_id


class RuleDeduplicator:
    """冷却/去重/确认期管理器"""

    DEFAULT_COOLDOWN_MINUTES = 60
    DEFAULT_CONFIRMATION_COUNT = 3
    MERGE_WINDOW_MINUTES = 5

    @classmethod
    def check_cooldown(cls, rule_id: str, cooldown_minutes: Optional[int] = None) -> bool:
        """检查冷却期：是否在冷却期内？

        Returns:
            True = 在冷却期内（应跳过推送）
            False = 不在冷却期内（可以推送）
        """
        cd = cooldown_minutes or cls.DEFAULT_COOLDOWN_MINUTES
        now = datetime.now()
        last_push = _cooldown_state.get(rule_id)

        if last_push is None:
            return False  # 从未推送过 → 不在冷却期

        elapsed = (now - last_push).total_seconds() / 60
        if elapsed < cd:
            logger.debug(f"规则 {rule_id} 冷却中: 已过 {elapsed:.1f}min / {cd}min")
            return True

        return False

    @classmethod
    def record_push(cls, rule_id: str) -> None:
        """记录一次推送时间"""
        _cooldown_state[rule_id] = datetime.now()

    @classmethod
    def check_merge_window(cls, rule_id: str) -> DedupResult:
        """检查是否应合并到已有通知（高频窗口内）

        5 分钟内同一规则的多次触发 → 合并到首次生成的那条通知。
        """
        now = datetime.now()
        last_push = _cooldown_state.get(rule_id)

        if last_push is None:
            return DedupResult()

        elapsed = (now - last_push).total_seconds() / 60
        if elapsed <= cls.MERGE_WINDOW_MINUTES:
            master_id = _merge_window_state.get(rule_id, '')
            return DedupResult(
                should_merge=True,
                master_notif_id=master_id,
                reason=f'高频合并: 距上次推送仅 {elapsed:.1f}min',
            )

        _merge_window_state.pop(rule_id, None)
        return DedupResult()

    @classmethod
    def record_merge_reference(cls, rule_id: str, notif_id: str) -> None:
        """记录合并参考通知 ID"""
        _merge_window_state[rule_id] = notif_id

    @classmethod
    def check_confirmation(cls, rule_id: str, passed: bool,
                           confirmation_required: Optional[int] = None) -> DedupResult:
        """确认期检查：条件需连续 N 次评估通过才推送

        Args:
            rule_id: 规则 ID
            passed: 本次评估是否通过
            confirmation_required: 所需连续通过次数（默认 3）

        Returns:
            DedupResult.should_delay = True 表示确认期未满，应推迟推送
            DedupResult.should_delay = False 表示确认期已满，可以推送
        """
        confirm_count = confirmation_required or _confirmation_settings.get(rule_id, cls.DEFAULT_CONFIRMATION_COUNT)

        if not passed:
            # 评估未通过 → 重置连续计数
            _interim_state[rule_id] = 0
            return DedupResult(
                should_delay=True,
                interim_count=0,
                confirmation_required=confirm_count,
                confirmation_achieved=0,
                reason='条件未通过，重置确认期计数',
            )

        # 条件已通过 → 递增计数
        current = _interim_state.get(rule_id, 0) + 1
        _interim_state[rule_id] = current

        if current < confirm_count:
            return DedupResult(
                should_delay=True,
                interim_count=current,
                confirmation_required=confirm_count,
                confirmation_achieved=current,
                reason=f'确认期: {current}/{confirm_count} 次连续通过',
            )

        # 确认期已满 → 重置计数并允许推送
        _interim_state[rule_id] = 0
        return DedupResult(
            should_delay=False,
            interim_count=current,
            confirmation_required=confirm_count,
            confirmation_achieved=current,
            reason=f'确认期完成: {current}/{confirm_count}',
        )

    @classmethod
    def set_confirmation_setting(cls, rule_id: str, count: int) -> None:
        """设置规则的确认期参数"""
        _confirmation_settings[rule_id] = max(1, count)

    @classmethod
    def get_interim_count(cls, rule_id: str) -> int:
        """获取当前连续通过计数"""
        return _interim_state.get(rule_id, 0)

    @classmethod
    def reset_rule(cls, rule_id: str) -> None:
        """重置某规则的全部状态（规则被暂停/删除时调用）"""
        _cooldown_state.pop(rule_id, None)
        _interim_state.pop(rule_id, None)
        _merge_window_state.pop(rule_id, None)

    @classmethod
    def get_cooldown_remaining(cls, rule_id: str) -> int:
        """获取冷却期剩余分钟数（0 表示冷却期已过）"""
        cd_config = _confirmation_settings.get(rule_id, cls.DEFAULT_CONFIRMATION_COUNT)
        last_push = _cooldown_state.get(rule_id)
        if last_push is None:
            return 0
        cd_minutes = cd_config * 20  # 按确认数推测冷却时间
        elapsed = (datetime.now() - last_push).total_seconds() / 60
        remaining = max(0, int(cd_minutes - elapsed))
        return remaining

    @classmethod
    def get_all_state_summary(cls) -> dict:
        """获取全状态摘要（用于健康检查/调试）"""
        now = datetime.now()
        cooldown_active = sum(1 for rid, t in _cooldown_state.items()
                              if (now - t).total_seconds() / 60 < cls.DEFAULT_COOLDOWN_MINUTES)
        return {
            'rules_in_cooldown': cooldown_active,
            'rules_in_interim': len(_interim_state),
            'total_tracked_rules': len(set(list(_cooldown_state.keys()) + list(_interim_state.keys()))),
            'cooldown_timestamps': {k: v.isoformat() for k, v in _cooldown_state.items()},
            'interim_counts': dict(_interim_state),
        }
