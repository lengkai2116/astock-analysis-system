"""
监控通知服务

规则CRUD业务逻辑 + 条件库查询 + 统计计算 + 休眠管理 + 评估协调
"""
import logging
from datetime import datetime, date, timedelta
from typing import Dict, List, Optional, Any

from app import db
from app.models.notification import NotificationRule, Notification, NotificationRuleStats, ReportArchive

logger = logging.getLogger(__name__)

_RULE_ID_COUNTER = 0  # 线程级简单计数器，生产环境应改用DB序列


def _next_rule_id() -> str:
    """生成规则ID: R-yyyymmdd-NNN"""
    global _RULE_ID_COUNTER
    _RULE_ID_COUNTER += 1
    today = date.today().strftime('%Y%m%d')
    return f'R-{today}-{_RULE_ID_COUNTER:03d}'


def _next_notif_id() -> str:
    """生成通知ID: N-yyyymmdd-NNN"""
    global _RULE_ID_COUNTER
    _RULE_ID_COUNTER += 1
    today = date.today().strftime('%Y%m%d')
    return f'N-{today}-{_RULE_ID_COUNTER:03d}'


# ─── 规则 CRUD ─────────────────────────────────────────────

def list_rules(status=None, rule_type=None, scope_type=None, search=None, sort='recent', limit=20, offset=0):
    """列出规则，支持筛选+排序+分页"""
    query = NotificationRule.query.filter(NotificationRule.deleted_at.is_(None))

    if status:
        query = query.filter(NotificationRule.status == status)
    if rule_type:
        query = query.filter(NotificationRule.rule_type == rule_type)
    if scope_type:
        query = query.filter(NotificationRule.scope_type == scope_type)
    if search:
        like = f'%{search}%'
        query = query.filter(
            db.or_(
                NotificationRule.name.ilike(like),
                NotificationRule.rule_id.ilike(like),
            )
        )

    # 排序
    if sort == 'created':
        query = query.order_by(NotificationRule.created_at.desc())
    elif sort == 'most':
        query = query.order_by(NotificationRule.trigger_total.desc())
    elif sort == 'hot':
        query = query.order_by(NotificationRule.hot_score.desc())
    elif sort == 'name':
        query = query.order_by(NotificationRule.name.asc())
    else:  # 'recent' 默认
        query = query.order_by(NotificationRule.last_trigger.desc().nullslast(),
                               NotificationRule.updated_at.desc())

    total = query.count()
    rules = query.offset(offset).limit(limit).all()

    return {
        'rules': [r.to_dict() for r in rules],
        'total': total,
        'limit': limit,
        'offset': offset,
    }


def get_rule(rule_id: str):
    """获取单条规则详情"""
    rule = NotificationRule.query.filter_by(rule_id=rule_id).first()
    if not rule or rule.deleted_at:
        return None

    result = rule.to_dict()

    # 最近20条触发历史
    recent = Notification.query \
        .filter_by(rule_id=rule_id) \
        .order_by(Notification.trigger_time.desc()) \
        .limit(20).all()

    result['history_summary'] = {
        'total': rule.trigger_total or 0,
        'recent': [n.to_dict() for n in recent],
    }
    return result


def create_rule(data: dict):
    """创建规则"""
    # 重复检测
    dup_conditions = data.get('conditions', [])
    dup_scope = data.get('scope', {}).get('type') or 'market'
    if dup_conditions:
        existing = NotificationRule.query.filter(
            NotificationRule.deleted_at.is_(None),
            NotificationRule.status.in_(['running', 'paused']),
        ).all()
        for r in existing:
            if (r.conditions == dup_conditions and
                    r.scope_type == dup_scope and
                    (r.scope_detail or {}).get('type') == data.get('scope', {}).get('type', '')):
                if r.conditions:
                    pass  # 匹配到了，但允许创建同名

    rule = NotificationRule(
        rule_id=_next_rule_id(),
        name=data.get('name', '未命名规则'),
        rule_type=data.get('type', 'opportunity'),
        status='running',
        scope_type=data.get('scope', {}).get('type', 'multi'),
        conditions=[{
            'condition_id': c.get('condition_id'),
            'params': c.get('params', {}),
        } for c in data.get('conditions', [])],
        condition_logic=data.get('condition_logic', 'AND'),
        scope_detail=data.get('scope', {}),
        schedule_start=data.get('schedule', {}).get('start', '09:30'),
        schedule_end=data.get('schedule', {}).get('end', '15:00'),
        scan_interval=data.get('scan_interval', 15),
        cooldown=data.get('cooldown', 30),
        channels=data.get('channels', {'desktop': True, 'wechat': False}),
        confirm_period=data.get('confirm_period', 0),
        long_term_monitor=data.get('long_term_monitor', False),
    )

    # 有效期
    if data.get('valid_from'):
        try:
            rule.valid_from = datetime.strptime(data['valid_from'][:10], '%Y-%m-%d').date()
        except ValueError:
            pass
    if data.get('valid_until'):
        try:
            rule.valid_until = datetime.strptime(data['valid_until'][:10], '%Y-%m-%d').date()
        except ValueError:
            pass

    db.session.add(rule)
    db.session.commit()

    return rule.to_dict()


def update_rule(rule_id: str, data: dict):
    """更新规则（部分更新）"""
    rule = NotificationRule.query.filter_by(rule_id=rule_id).first()
    if not rule or rule.deleted_at:
        return None

    updates = {
        'name': 'name',
        'type': 'rule_type',
        'status': 'status',
        'condition_logic': 'condition_logic',
        'scan_interval': 'scan_interval',
        'cooldown': 'cooldown',
        'confirm_period': 'confirm_period',
        'long_term_monitor': 'long_term_monitor',
    }
    for key, attr in updates.items():
        if key in data:
            setattr(rule, attr, data[key])

    if 'conditions' in data:
        rule.conditions = [{'condition_id': c.get('condition_id'), 'params': c.get('params', {})}
                           for c in data['conditions']]
    if 'scope' in data:
        rule.scope_detail = data['scope']
        if 'type' in data['scope']:
            rule.scope_type = data['scope']['type']
    if 'schedule' in data:
        s = data['schedule']
        if 'start' in s:
            rule.schedule_start = s['start']
        if 'end' in s:
            rule.schedule_end = s['end']
    if 'channels' in data:
        rule.channels = data['channels']
    if 'valid_from' in data and data['valid_from']:
        try:
            rule.valid_from = datetime.strptime(data['valid_from'][:10], '%Y-%m-%d').date()
        except ValueError:
            pass
    if 'valid_until' in data and data['valid_until']:
        try:
            rule.valid_until = datetime.strptime(data['valid_until'][:10], '%Y-%m-%d').date()
        except ValueError:
            pass

    db.session.commit()
    return rule.to_dict()


def delete_rule(rule_id: str):
    """软删除规则"""
    rule = NotificationRule.query.filter_by(rule_id=rule_id).first()
    if not rule:
        return False
    rule.deleted_at = datetime.now()
    rule.status = 'deleted'
    db.session.commit()
    return True


def clone_rule(rule_id: str):
    """克隆规则"""
    rule = NotificationRule.query.filter_by(rule_id=rule_id).first()
    if not rule or rule.deleted_at:
        return None

    new_rule = NotificationRule(
        rule_id=_next_rule_id(),
        name=rule.name + ' (副本)',
        rule_type=rule.rule_type,
        status='paused',  # 克隆默认暂停，用户手动启用
        scope_type=rule.scope_type,
        conditions=rule.conditions,
        condition_logic=rule.condition_logic,
        scope_detail=rule.scope_detail,
        schedule_start=rule.schedule_start,
        schedule_end=rule.schedule_end,
        scan_interval=rule.scan_interval,
        cooldown=rule.cooldown,
        channels=rule.channels,
        confirm_period=rule.confirm_period,
        long_term_monitor=rule.long_term_monitor,
        valid_from=rule.valid_from,
        valid_until=rule.valid_until,
    )
    db.session.add(new_rule)
    db.session.commit()
    return new_rule.to_dict()


def batch_operation(rule_ids: list, action: str):
    """批量操作：pause / resume / delete"""
    results = {'success': [], 'skipped': []}
    for rid in rule_ids:
        rule = NotificationRule.query.filter_by(rule_id=rid).first()
        if not rule or rule.deleted_at:
            results['skipped'].append(rid)
            continue
        if action == 'pause':
            rule.status = 'paused'
        elif action == 'resume':
            rule.status = 'running'
        elif action == 'delete':
            rule.deleted_at = datetime.now()
            rule.status = 'deleted'
        results['success'].append(rid)
    db.session.commit()
    return results


# ─── 通知查询 ─────────────────────────────────────────────

def list_recent_notifications(limit=20, unread_only=True):
    """最近通知列表"""
    query = Notification.query
    if unread_only:
        query = query.filter(Notification.is_unread.is_(True))
    query = query.order_by(Notification.trigger_time.desc()).limit(limit)
    notifs = query.all()
    unread_count = Notification.query.filter(Notification.is_unread.is_(True)).count()

    return {
        'notifications': [n.to_dict() for n in notifs],
        'unread_count': unread_count,
    }


def get_today_unread():
    """今日未处理通知（顶部滚动区用）"""
    today_start = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
    notifs = Notification.query \
        .filter(Notification.is_unread.is_(True),
                Notification.trigger_time >= today_start) \
        .order_by(Notification.trigger_time.desc()) \
        .limit(10).all()

    # 无未读通知时返回运行中的规则
    cards = []
    if notifs:
        for n in notifs:
            stock = n.stock or {}
            cards.append({
                'stock': stock.get('name', ''),
                'change': n.trigger_value or '',
                'type': n.notif_type,
                'tag': n.notif_type,
            })
    else:
        running_rules = NotificationRule.query \
            .filter(NotificationRule.status == 'running',
                    NotificationRule.deleted_at.is_(None)) \
            .order_by(NotificationRule.updated_at.desc()) \
            .limit(5).all()
        cards = [{'stock': r.name, 'change': '', 'type': 'status', 'tag': '运行中'}
                 for r in running_rules]

    return {
        'cards': cards,
        'header_text': f'{len(cards)} 条运行中',
    }


def get_summary():
    """汇总统计（页面头部统计条）"""
    total = NotificationRule.query.filter(NotificationRule.deleted_at.is_(None)).count()
    active = NotificationRule.query.filter(
        NotificationRule.status == 'running',
        NotificationRule.deleted_at.is_(None),
    ).count()
    paused = NotificationRule.query.filter(
        NotificationRule.status.in_(['paused', 'dormant']),
        NotificationRule.deleted_at.is_(None),
    ).count()

    today_start = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
    today_triggered = Notification.query \
        .filter(Notification.trigger_time >= today_start) \
        .count()

    # 按类型分布
    type_counts = {}
    for t in ['opportunity', 'risk', 'anomaly', 'status', 'discipline']:
        type_counts[t] = NotificationRule.query.filter(
            NotificationRule.rule_type == t,
            NotificationRule.deleted_at.is_(None),
            NotificationRule.status == 'running',
        ).count()

    return {
        'total': total,
        'today_triggered': today_triggered,
        'active': active,
        'paused': paused,
        'by_type': type_counts,
    }


def acknowledge(rule_id: str, action: str = ''):
    """隐式确认通知"""
    notif = Notification.query \
        .filter(Notification.rule_id == rule_id, Notification.is_unread.is_(True)) \
        .order_by(Notification.trigger_time.desc()) \
        .first()
    if not notif:
        return {'unread_count': _get_unread_count()}

    notif.is_unread = False
    notif.ack_action = action or 'viewed'
    notif.acked_at = datetime.now()
    db.session.commit()

    return {'unread_count': _get_unread_count()}


def _get_unread_count():
    return Notification.query.filter(Notification.is_unread.is_(True)).count()


# ─── 休眠管理 ─────────────────────────────────────────────

def get_dormant_rules():
    """获取休眠区规则列表"""
    rules = NotificationRule.query.filter(
        NotificationRule.status.in_(['dormant', 'paused']),
        NotificationRule.deleted_at.is_(None),
        NotificationRule.dormant_since.isnot(None),
    ).order_by(NotificationRule.dormant_since.desc()).all()

    return [{
        'name': r.name,
        'rule_id': r.rule_id,
        'type': r.rule_type,
        'last_trigger': r.last_trigger.isoformat() if r.last_trigger else None,
        'dormant_days': (datetime.now() - r.dormant_since).days if r.dormant_since else 0,
        'condition': r.conditions[0].get('name', '') if r.conditions else '',
    } for r in rules]


def get_health_check():
    """健康检查（L3: 暂停30+天规则）"""
    thirty_days_ago = datetime.now() - timedelta(days=30)
    rules = NotificationRule.query.filter(
        NotificationRule.status.in_(['dormant', 'paused']),
        NotificationRule.deleted_at.is_(None),
        NotificationRule.dormant_since.isnot(None),
        NotificationRule.dormant_since <= thirty_days_ago,
    ).all()

    return {
        'count': len(rules),
        'dormant_days': '30+',
        'rules': [{
            'rule_id': r.rule_id,
            'name': r.name,
            'type': r.rule_type,
            'dormant_days': (datetime.now() - r.dormant_since).days,
        } for r in rules],
    }


# ─── 触发历史 ─────────────────────────────────────────────

def list_history(rule_id=None, stock_code=None, page=1, per_page=20, start_date=None, end_date=None):
    """触发历史列表"""
    query = Notification.query

    if rule_id:
        query = query.filter(Notification.rule_id == rule_id)
    if stock_code:
        query = query.filter(Notification.stock['ts_code'].as_string().ilike(f'%{stock_code}%'))
    if start_date:
        try:
            sd = datetime.strptime(start_date, '%Y-%m-%d')
            query = query.filter(Notification.trigger_time >= sd)
        except ValueError:
            pass
    if end_date:
        try:
            ed = datetime.strptime(end_date, '%Y-%m-%d') + timedelta(days=1)
            query = query.filter(Notification.trigger_time < ed)
        except ValueError:
            pass

    query = query.order_by(Notification.trigger_time.desc())
    pagination = query.paginate(page=page, per_page=per_page, error_out=False)

    return {
        'items': [n.to_dict() for n in pagination.items],
        'total': pagination.total,
        'page': pagination.page,
        'per_page': pagination.per_page,
        'pages': pagination.pages,
    }


# ─── 评估协调器 (Phase 2) ───────────────────────────────────

def run_evaluation(mode: str = 'intraday') -> dict:
    """规则评估协调器 — 串联 ConditionEvaluator + Deduplicator + Pusher

    Args:
        mode: 'intraday'（盘中定时扫描）或 'daily'（日终批量评估）

    Returns:
        dict: {
            'evaluated': 评估的规则数,
            'triggered': 触发的通知数,
            'errors': 出错数,
            'details': [{rule_id, passed, notif_id, ...}]
        }
    """
    from app.services.rule_scheduler import RuleScheduler
    from app.services.condition_evaluator import ConditionEvaluator
    from app.services.rule_deduplicator import RuleDeduplicator
    from app.services.notification_pusher import NotificationPusher

    evaluator = ConditionEvaluator()
    result_summary = {
        'mode': mode,
        'evaluated': 0,
        'triggered': 0,
        'errors': 0,
        'skipped_cooldown': 0,
        'skipped_schedule': 0,
        'skipped_confirm': 0,
        'details': [],
        'evaluated_at': datetime.now().isoformat(),
    }

    # 1. 查询所有运行中的规则
    rules = NotificationRule.query.filter(
        NotificationRule.status == 'running',
        NotificationRule.deleted_at.is_(None),
    ).all()

    if not rules:
        logger.info(f"评估完成: 无运行中的规则 ({mode})")
        return result_summary

    logger.info(f"开始评估: {len(rules)} 条规则 ({mode})")

    # 2. 逐规则评估
    for rule in rules:
        rule_id = getattr(rule, 'rule_id', '')
        if not rule_id:
            continue

        try:
            result_summary['evaluated'] += 1

            # 2a. 检查调度时段
            if not RuleScheduler.is_in_schedule_window(rule):
                result_summary['skipped_schedule'] += 1
                continue

            # 2b. 执行条件评估
            rule_dict = rule.to_dict()
            eval_result = evaluator.evaluate_rule(rule_dict)

            if not eval_result.passed:
                # 条件未通过 → 重置确认期计数
                if rule.confirm_period and rule.confirm_period > 0:
                    RuleDeduplicator.check_confirmation(rule_id, passed=False)
                continue

            # 2c. 冷却期检查
            if RuleDeduplicator.check_cooldown(rule_id, rule.cooldown):
                result_summary['skipped_cooldown'] += 1
                continue

            # 2d. 确认期检查（仅在启用时）
            if rule.confirm_period and rule.confirm_period > 0:
                confirm_result = RuleDeduplicator.check_confirmation(
                    rule_id, passed=True,
                    confirmation_required=rule.confirm_period,
                )
                if confirm_result.should_delay:
                    result_summary['skipped_confirm'] += 1
                    continue

            # 2e. 高频合并检查
            merge_result = RuleDeduplicator.check_merge_window(rule_id)
            if merge_result.should_merge:
                # 合并：更新已有通知的 today_count
                master_notif = Notification.query.filter_by(
                    notif_id=merge_result.master_notif_id
                ).first()
                if master_notif:
                    master_notif.today_count = (master_notif.today_count or 1) + 1
                    db.session.commit()
                result_summary['triggered'] += 1
                result_summary['details'].append({
                    'rule_id': rule_id,
                    'passed': True,
                    'merged': True,
                    'merged_to': merge_result.master_notif_id,
                })
                continue

            # 2f. 创建通知记录
            stock_code = rule_dict.get('scope_detail', {}).get('stock', '')
            stock_name = rule_dict.get('scope_detail', {}).get('stock_name', '')
            notif_id = _next_notif_id()

            notification = Notification(
                notif_id=notif_id,
                rule_id=rule_id,
                rule_name=getattr(rule, 'name', ''),
                notif_type=getattr(rule, 'rule_type', 'opportunity'),
                stock={'ts_code': stock_code, 'name': stock_name},
                trigger_time=datetime.now(),
                trigger_value=_summarize_trigger_value(eval_result),
                today_count=1,
                conditions_result=[{
                    'condition_id': r.condition_id,
                    'passed': r.passed,
                    'current_value': str(r.current_value) if r.current_value is not None else None,
                    'threshold': str(r.threshold) if r.threshold is not None else None,
                    'details': r.details,
                    'stock_code': r.stock_code,
                } for r in eval_result.condition_results],
                stock_info={
                    'ts_code': stock_code,
                    'stock_name': stock_name,
                },
                is_unread=True,
                channels_sent=[],
                deadline=datetime.now() + timedelta(minutes=rule.cooldown or 30) if rule.cooldown else None,
                cooldown_remaining=rule.cooldown or 30,
            )
            db.session.add(notification)

            # 2g. 更新规则统计
            rule.trigger_total = (rule.trigger_total or 0) + 1
            rule.trigger_today = (rule.trigger_today or 0) + 1
            rule.last_trigger = datetime.now()
            rule.hot_score = _recalc_hot_score(rule)

            # 2h. 更新日统计
            _update_daily_stats(rule_id)

            db.session.commit()

            # 2i. 记录冷却状态
            RuleDeduplicator.record_push(rule_id)
            RuleDeduplicator.record_merge_reference(rule_id, notif_id)

            # 2j. 推送通知
            channels = (rule.channels or {}).copy()
            active_channels = [ch for ch, enabled in channels.items() if enabled]
            if not active_channels:
                active_channels = ['desktop', 'popup']

            notif_dict = notification.to_dict()
            notif_dict.update({
                'rule_name': getattr(rule, 'name', ''),
                'rule_type': getattr(rule, 'rule_type', ''),
                'title': _build_notification_title(rule, eval_result),
                'message': _build_notification_message(eval_result),
                'stock_name': stock_name,
                'ts_code': stock_code,
                'level': _map_type_to_level(getattr(rule, 'rule_type', '')),
            })
            NotificationPusher.push_all(notif_dict, channels=active_channels)

            result_summary['triggered'] += 1
            result_summary['details'].append({
                'rule_id': rule_id,
                'passed': True,
                'notif_id': notif_id,
                'channels': active_channels,
            })

            logger.info(f"规则触发: {rule_id} → {notif_id} ({', '.join(active_channels)})")

        except Exception as e:
            logger.error(f"规则评估异常 {rule_id}: {e}")
            result_summary['errors'] += 1
            result_summary['details'].append({
                'rule_id': rule_id,
                'passed': False,
                'error': str(e),
            })

    logger.info(
        f"评估完成 ({mode}): {result_summary['evaluated']}规则 "
        f"→ {result_summary['triggered']}触发 "
        f"/ {result_summary['skipped_cooldown']}冷却 "
        f"/ {result_summary['skipped_schedule']}非时段 "
        f"/ {result_summary['skipped_confirm']}确认期 "
        f"/ {result_summary['errors']}错误"
    )
    return result_summary


def _recalc_hot_score(rule) -> float:
    """重新计算热度评分"""
    total = rule.trigger_total or 0
    today = rule.trigger_today or 0
    return total * 0.3 + today * 0.7


def _update_daily_stats(rule_id: str) -> None:
    """更新日统计"""
    today = date.today()
    stats = NotificationRuleStats.query.filter_by(
        rule_id=rule_id, stat_date=today
    ).first()
    if not stats:
        stats = NotificationRuleStats(
            rule_id=rule_id,
            stat_date=today,
            trigger_count=1,
            pass_count=1,
        )
        db.session.add(stats)
    else:
        stats.trigger_count = (stats.trigger_count or 0) + 1
        stats.pass_count = (stats.pass_count or 0) + 1


def _summarize_trigger_value(eval_result) -> str:
    """从评估结果中提炼关键触发值"""
    parts = []
    for r in eval_result.condition_results:
        if r.passed and r.current_value is not None:
            parts.append(f'{r.condition_id}={r.current_value}')
    return ', '.join(parts[:3])


def _build_notification_title(rule, eval_result) -> str:
    """构建通知标题"""
    type_prefix = {
        'opportunity': '📈',
        'risk': '🛡️',
        'anomaly': '⚡',
        'status': '📋',
        'discipline': '🎯',
    }
    prefix = type_prefix.get(getattr(rule, 'rule_type', ''), '📌')
    return f'{prefix} {getattr(rule, "name", "监控通知")}'


def _build_notification_message(eval_result) -> str:
    """构建通知消息"""
    messages = []
    for r in eval_result.condition_results:
        if r.passed:
            messages.append(f'✅ {r.details}')
        else:
            messages.append(f'⏹️ {r.details}')
    return '\n'.join(messages[:5])


def _map_type_to_level(rule_type: str) -> str:
    """规则类型 → 通知级别"""
    mapping = {
        'opportunity': 'info',
        'risk': 'high',
        'anomaly': 'warning',
        'status': 'info',
        'discipline': 'info',
    }
    return mapping.get(rule_type, 'info')


# ══════════════════════════════════════════════════════════════
# Phase 3: 增强功能
# ══════════════════════════════════════════════════════════════

# ─── 3.1 触发历史增强 ────────────────────────────────────────

def list_history_enhanced(rule_id=None, stock_code=None, page=1, per_page=20,
                          start_date=None, end_date=None,
                          notif_type=None, is_unread=None,
                          sort='time_desc', rule_name=None):
    """增强版触发历史列表（支持类型筛选+排序+关键词）"""
    query = Notification.query

    if rule_id:
        query = query.filter(Notification.rule_id == rule_id)
    if stock_code:
        query = query.filter(Notification.stock['ts_code'].as_string().ilike(f'%{stock_code}%'))
    if notif_type:
        query = query.filter(Notification.notif_type == notif_type)
    if is_unread is not None:
        query = query.filter(Notification.is_unread.is_(is_unread))
    if rule_name:
        query = query.filter(Notification.rule_name.ilike(f'%{rule_name}%'))
    if start_date:
        try:
            sd = datetime.strptime(start_date, '%Y-%m-%d')
            query = query.filter(Notification.trigger_time >= sd)
        except ValueError:
            pass
    if end_date:
        try:
            ed = datetime.strptime(end_date, '%Y-%m-%d') + timedelta(days=1)
            query = query.filter(Notification.trigger_time < ed)
        except ValueError:
            pass

    if sort == 'time_asc':
        query = query.order_by(Notification.trigger_time.asc())
    else:
        query = query.order_by(Notification.trigger_time.desc())

    pagination = query.paginate(page=page, per_page=per_page, error_out=False)

    return {
        'items': [n.to_dict() for n in pagination.items],
        'total': pagination.total,
        'page': pagination.page,
        'per_page': pagination.per_page,
        'pages': pagination.pages,
        'summary': _history_summary(rule_id, start_date, end_date),
    }


def _history_summary(rule_id=None, start_date=None, end_date=None) -> dict:
    """触发历史摘要统计"""
    query = Notification.query
    if rule_id:
        query = query.filter(Notification.rule_id == rule_id)
    if start_date:
        try:
            query = query.filter(Notification.trigger_time >= datetime.strptime(start_date, '%Y-%m-%d'))
        except ValueError:
            pass
    if end_date:
        try:
            query = query.filter(Notification.trigger_time < datetime.strptime(end_date, '%Y-%m-%d') + timedelta(days=1))
        except ValueError:
            pass

    all_notifs = query.all()
    total = len(all_notifs)
    unread = sum(1 for n in all_notifs if n.is_unread)

    type_counts = {}
    for n in all_notifs:
        t = n.notif_type or 'unknown'
        type_counts[t] = type_counts.get(t, 0) + 1

    return {
        'total': total,
        'unread': unread,
        'by_type': type_counts,
    }


# ─── 3.2 导出 CSV ───────────────────────────────────────────

def export_history_csv(rule_id=None, stock_code=None,
                       start_date=None, end_date=None,
                       notif_type=None, limit=5000) -> str:
    """导出触发历史为 CSV 文本

    Returns:
        CSV 格式字符串（含 UTF-8 BOM，适合 Excel 直接打开）
    """
    query = Notification.query

    if rule_id:
        query = query.filter(Notification.rule_id == rule_id)
    if stock_code:
        query = query.filter(Notification.stock['ts_code'].as_string().ilike(f'%{stock_code}%'))
    if notif_type:
        query = query.filter(Notification.notif_type == notif_type)
    if start_date:
        try:
            query = query.filter(Notification.trigger_time >= datetime.strptime(start_date, '%Y-%m-%d'))
        except ValueError:
            pass
    if end_date:
        try:
            query = query.filter(Notification.trigger_time < datetime.strptime(end_date, '%Y-%m-%d') + timedelta(days=1))
        except ValueError:
            pass

    notifs = query.order_by(Notification.trigger_time.desc()).limit(limit).all()

    lines = [
        '﻿通知ID,规则ID,规则名称,类型,股票代码,股票名称,触发时间,触发值,今日计数,已读,确认动作,' +
        '截止时间,创建时间'
    ]

    for n in notifs:
        stock = n.stock or {}
        ts_code = stock.get('ts_code', '')
        stock_name = stock.get('name', '')
        trigger = n.trigger_time.isoformat() if n.trigger_time else ''
        deadline = n.deadline.isoformat() if n.deadline else ''
        created = n.created_at.isoformat() if n.created_at else ''

        # CSV 转义
        def esc(val):
            s = str(val)
            if ',' in s or '"' in s or '\n' in s:
                return '"' + s.replace('"', '""') + '"'
            return s

        lines.append(','.join([
            esc(n.notif_id),
            esc(n.rule_id),
            esc(n.rule_name or ''),
            esc(n.notif_type or ''),
            esc(ts_code),
            esc(stock_name),
            esc(trigger),
            esc(n.trigger_value or ''),
            str(n.today_count or 1),
            str(not n.is_unread) if n.is_unread is not None else '',
            esc(n.ack_action or ''),
            esc(deadline),
            esc(created),
        ]))

    return '\n'.join(lines)


# ─── 3.3 健康报告关联 report 中心 ────────────────────────────

def generate_health_report(rule_id: str = '') -> dict:
    """生成健康报告并关联到 report 中心

    Args:
        rule_id: 指定规则（空字符串则生成所有规则的汇总报告）

    Returns:
        dict: {report_id, report_type, rules_analyzed, summary}
    """
    from app.services.dormancy_manager import DormancyManager

    # 查询目标规则
    rules_query = NotificationRule.query.filter(NotificationRule.deleted_at.is_(None))
    if rule_id:
        rules_query = rules_query.filter(NotificationRule.rule_id == rule_id)

    all_rules = rules_query.all()
    running = [r for r in all_rules if r.status == 'running']
    paused = [r for r in all_rules if r.status in ('paused', 'dormant')]
    archived = [r for r in all_rules if r.status == 'deleted' and r.deleted_at]

    # 分析统计
    today = date.today()
    total_trigger = Notification.query.count()
    today_trigger = Notification.query.filter(
        Notification.trigger_time >= datetime.now().replace(hour=0, minute=0, second=0)
    ).count()

    # 休眠汇总
    dormant_summary = DormancyManager.run_weekly_health_report(all_rules)

    # 规则类型分布
    type_dist = {}
    for r in running:
        t = r.rule_type or 'unknown'
        type_dist[t] = type_dist.get(t, 0) + 1

    report_data = {
        'generated_at': datetime.now().isoformat(),
        'period': {
            'start': (today - timedelta(days=30)).isoformat(),
            'end': today.isoformat(),
        },
        'summary': {
            'total_rules': len(all_rules),
            'running': len(running),
            'paused': len(paused),
            'archived': len(archived),
            'total_triggers': total_trigger,
            'today_triggers': today_trigger,
        },
        'type_distribution': type_dist,
        'dormancy': dormant_summary,
        'rules': [r.to_dict() for r in all_rules],
    }

    # 写入 ReportArchive
    try:
        report = ReportArchive(
            report_type='diagnosis',
            source='notification',
            source_id=rule_id or '__all__',
            period_start=today - timedelta(days=30),
            period_end=today,
            generated_at=datetime.now(),
            file_path='',
            total_triggers=total_trigger,
            active_rules=len(running),
            stocks_covered=len(running),
            delivery_rate=len(running) / max(len(all_rules), 1),
        )
        db.session.add(report)
        db.session.commit()
        report_id = report.id
    except Exception as e:
        logger.warning(f"健康报告写入 ReportArchive 失败: {e}")
        report_id = None

    # 返回结果（报告中心关联通过 ReportArchive 记录实现）
    return {
        'report_id': report_id,
        'report_center_id': None,  # 可通过 POST /api/v3/reports 手动推送
        'report_type': 'diagnosis',
        'rules_analyzed': len(all_rules),
        'summary': report_data['summary'],
    }


# ─── 3.4 批量下载（端点入口） ────────────────────────────────

def get_download_records(record_type: str = 'csv', **filters) -> Any:
    """获取下载数据

    Args:
        record_type: 'csv' 或 'json'
        filters: 筛选参数（rule_id, stock_code, start_date, end_date, notif_type）

    Returns:
        str (csv) 或 list[dict] (json)
    """
    query = Notification.query

    rule_id = filters.get('rule_id')
    stock_code = filters.get('stock_code')
    start_date = filters.get('start_date')
    end_date = filters.get('end_date')
    notif_type = filters.get('notif_type')

    if rule_id:
        query = query.filter(Notification.rule_id == rule_id)
    if stock_code:
        query = query.filter(Notification.stock['ts_code'].as_string().ilike(f'%{stock_code}%'))
    if notif_type:
        query = query.filter(Notification.notif_type == notif_type)
    if start_date:
        try:
            query = query.filter(Notification.trigger_time >= datetime.strptime(start_date, '%Y-%m-%d'))
        except ValueError:
            pass
    if end_date:
        try:
            query = query.filter(Notification.trigger_time < datetime.strptime(end_date, '%Y-%m-%d') + timedelta(days=1))
        except ValueError:
            pass

    notifs = query.order_by(Notification.trigger_time.desc()).limit(5000).all()
    items = [n.to_dict() for n in notifs]

    if record_type == 'csv':
        return export_history_csv(rule_id=rule_id, stock_code=stock_code,
                                  start_date=start_date, end_date=end_date,
                                  notif_type=notif_type)
    return items


# ─── 3.5 提交重推任务到调度器 ─────────────────────────────────

def register_retry_job(scheduler_manager) -> None:
    """注册倒计时重推定时任务（每15分钟）"""
    from app.services.notification_pusher import NotificationPusher

    def retry_job():
        result = NotificationPusher.run_retry_check()
        if result['retried'] > 0 or result['errors'] > 0:
            logger.info(f"重推检查: checked={result['checked']} retried={result['retried']} errors={result['errors']}")

    scheduler_manager.add_interval_job(
        job_id='notification_retry_check',
        func=retry_job,
        minutes=15,
        max_instances=1,
        coalesce=True,
    )
    logger.info("倒计时重推任务已注册 (每15分钟)")
