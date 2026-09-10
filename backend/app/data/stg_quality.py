"""423号方案：STG 仓储质量体系（WriteGateway + QualityChecker + RecomputeScheduler）

分层定位（v2.0 架构修订）：
- sharding_manager（既有）：表→库路由、分库级 _write_locks 串行化、INSERT OR REPLACE 幂等
- WriteGateway（薄封装）：写前格式校验 → 委托 sharding_manager 执行 → 写后行数校验 → 审计日志
- QualityChecker：按表质量规则（动态覆盖率基准）单表/跨表校验 + SIG 结果自检（G3）
- RecomputeScheduler：问题→责任环节映射（执行器由 daemon 侧注入，本模块不依赖采集/计算函数）

校验基准（423号 §2.3）：以 daily_cache 目标日期行数 N 为锚，各表行数 ≥ N×rows_ratio。
修正 v1.0 缺陷：累积表（factor_cache 等）按当日批次校验，不按全表行数。
"""
from __future__ import annotations

import json
import logging
import time
from dataclasses import dataclass, field
from typing import Callable, Optional

logger = logging.getLogger(__name__)

# ── 校验规则注册表（423号 §2.3 QUALITY_RULES）────────────────────
# rows_ratio: 对 daily_cache 目标日期行数 N 的覆盖率基准
# date_col:    日期过滤列（全部为 trade_date）
# distinct_ts: True 时按 COUNT(DISTINCT ts_code) 统计（多行/股的表）
# required_fields / json_fields / seven_dim_keys
QUALITY_RULES: dict[str, dict] = {
    'daily_cache': {'rows_ratio': 1.00, 'date_col': 'trade_date'},
    'indicator_ma': {
        'rows_ratio': 0.95, 'date_col': 'trade_date',
        'required_fields': ['ma5', 'ma20'],
    },
    'indicator_macd': {
        'rows_ratio': 0.95, 'date_col': 'trade_date',
        'required_fields': ['macd_dif'],
    },
    'indicator_other': {
        'rows_ratio': 0.95, 'date_col': 'trade_date',
        'required_fields': ['rsi14'],
    },
    'pre_feat_cache': {
        'rows_ratio': 0.95, 'date_col': 'trade_date',
        'json_fields': ['features_json'],
    },
    'factor_cache': {
        'rows_ratio': 0.95, 'date_col': 'trade_date', 'distinct_ts': True,
    },
    'strategy_signal_detail': {
        'rows_ratio': 0.95, 'date_col': 'trade_date',
        'required_fields': ['signal_json', 'dim_results_json'],
        'json_fields': ['signal_json', 'dim_results_json', 'seven_dim_json'],
        # seven_dim_json 为条件性产出（status_engine.generate_seven_dim_from_signals：
        # 仅 risk/summary 恒产出，其余维需对应引擎有信号），故不要求固定 7 键，
        # 只要求可解析且含恒产出的 summary 键
        'seven_dim_required': ['summary'],
    },
    'status_snapshot': {
        'rows_ratio': 0.95, 'date_col': 'trade_date',
        'required_fields': ['dim_states', 'status_bar'],
    },
    'treemap_snapshot': {'rows_ratio': 0.95, 'date_col': 'trade_date'},
}

# SIG 批量写入 rows tuple 的字段索引（对齐 _batch_write_signal_detail 的 INSERT 列序）
_SIG_ROW_IDX = {
    'ts_code': 0, 'trade_date': 1, 'signal_json': 2,
    'schema_version': 3, 'seven_dim_json': 4, 'dim_results_json': 5,
}

# 写锁冲突计数（G7：进程内聚合，供 monitor/health 消费）
_write_lock_conflicts: dict[str, int] = {}


def get_write_lock_conflicts() -> dict:
    """返回写锁冲突计数（按表聚合）"""
    return dict(_write_lock_conflicts)


def _record_write_lock(table: str):
    _write_lock_conflicts[table] = _write_lock_conflicts.get(table, 0) + 1


# ── 校验结果类型 ────────────────────────────────────────────────

@dataclass
class CheckResult:
    """单表/单校验项结果"""
    passed: bool
    table: str = ''
    pipeline_date: str = ''
    expected: int = 0
    actual: int = 0
    issues: list = field(default_factory=list)
    severity: str = 'LOW'
    kind: str = 'table'          # table | cross | signal

    def to_dict(self) -> dict:
        return {
            'passed': self.passed, 'table': self.table,
            'pipeline_date': self.pipeline_date,
            'expected': self.expected, 'actual': self.actual,
            'issues': self.issues, 'severity': self.severity, 'kind': self.kind,
        }


def _resolve_ecm(ecm=None):
    """获取 ECM 实例（延迟导入，避免循环依赖）"""
    if ecm is not None:
        return ecm
    from app.data.enhanced_cache_manager import get_ecm_instance
    return get_ecm_instance()


def _resolve_sharding():
    from app.data.sharding_manager import sharding_manager
    return sharding_manager


# ── 组件 1：WriteGateway（薄封装，423号 §2.2）────────────────────

class WriteGateway:
    """统一写入网关——sharding_manager 之上的薄封装

    职责：写前格式校验 → 委托 sharding_manager 执行（锁/事务/幂等）
         → 写后行数校验 → 写入审计日志。
    不持有锁、不建连接池；锁与事务全部委托既有 sharding_manager。
    """

    def __init__(self, ecm=None):
        self._ecm = ecm
        self._sm = _resolve_sharding()

    # ── 写前校验 ──
    def validate_before_write(self, table: str, rows: list) -> list:
        """写前格式校验：返回问题列表（空列表 = 通过）"""
        issues: list = []
        if not rows:
            return [f'{table}: 空写入（rows=0），已拒绝']
        # rows 为位置元组时无法按列名校验；此处仅校验基本结构
        for i, row in enumerate(rows):
            if not isinstance(row, (list, tuple)):
                issues.append(f'{table}: 第{i}行不是序列类型')
                if len(issues) > 10:
                    break
        return issues

    # ── 写后校验（行数覆盖率，基于 daily_cache 基准或期望值）──
    def validate_after_write(self, table: str, pipeline_date: str,
                             expected_count: Optional[int] = None) -> CheckResult:
        """写后行数校验：实际行数 ≥ max(expected×0.95, N×rows_ratio×0.95)"""
        rule = QUALITY_RULES.get(table, {})
        ratio = rule.get('rows_ratio', 0.95)
        date_col = rule.get('date_col', 'trade_date')
        distinct = rule.get('distinct_ts', False)
        count_expr = 'COUNT(DISTINCT ts_code)' if distinct else 'COUNT(*)'
        try:
            conn = self._sm.get_connection(self._sm.get_db_for_table(table))
            actual = conn.execute(
                f'SELECT {count_expr} FROM {table} WHERE {date_col}=?', [pipeline_date]
            ).fetchone()[0] or 0
        except Exception as e:
            return CheckResult(False, table, pipeline_date, issues=[f'写后校验查询失败: {e}'],
                               severity='HIGH')
        base = expected_count if expected_count else self._daily_base(pipeline_date)
        threshold = int(base * ratio)
        if actual < threshold:
            return CheckResult(
                False, table, pipeline_date, expected=threshold, actual=actual,
                issues=[f'{table} 行数不足: 期望≥{threshold}, 实际 {actual}'],
                severity='HIGH')
        return CheckResult(True, table, pipeline_date, expected=threshold, actual=actual)

    # ── 主入口 ──
    def write_batch(self, table: str, rows: list, pipeline_date: str,
                    insert_sql: str,
                    expected_ratio: float = 0.95,
                    fail_on_validate: bool = False,
                    raise_exc: Optional[type] = None) -> CheckResult:
        """批量写入全流程：写前校验 → 委托 sharding_manager → 写后校验 → 审计

        insert_sql 必填（sharding_manager.execute_batch_insert 需完整 SQL）。
        返回写后校验 CheckResult；fail_on_validate=True 且写前校验失败时
        抛出 raise_exc（默认 ValueError），用于 G3/SIG 场景。
        """
        pre_issues = self.validate_before_write(table, rows)
        if pre_issues and fail_on_validate:
            exc = raise_exc or ValueError
            raise exc(f'{table} 写前校验失败: {"; ".join(pre_issues[:5])}')
        if pre_issues:
            logger.warning(f'{table} 写前校验告警（继续写入）: {pre_issues[:3]}')

        try:
            self._sm.execute_batch_insert(table, insert_sql, rows)
        except Exception as e:
            # G7：写锁冲突计数（database is locked 场景）
            if 'locked' in str(e).lower():
                _record_write_lock(table)
            raise

        result = self.validate_after_write(table, pipeline_date,
                                           expected_count=len(rows))
        self.write_audit(table, pipeline_date, rows=len(rows), result=result)
        return result

    # ── 审计日志（qa_audit_log）──
    def write_audit(self, table: str, pipeline_date: str, rows: int = 0,
                    result: Optional[CheckResult] = None,
                    extra: str = ''):
        """写入 qa_audit_log（幂等：同 pipeline_date+table 覆盖）"""
        ecm = _resolve_ecm(self._ecm)
        detail = extra
        if result is not None:
            detail = json.dumps(result.to_dict(), ensure_ascii=False)
        try:
            ecm.conn.execute(
                "INSERT OR REPLACE INTO qa_audit_log "
                "(pipeline_date, table_name, row_count, status, detail, checked_at) "
                "VALUES (?, ?, ?, ?, ?, datetime('now','localtime'))",
                [pipeline_date, table, rows,
                 'passed' if (result is None or result.passed) else 'failed', detail])
            ecm.conn.commit()
        except Exception as e:
            logger.warning(f'qa_audit_log 写入失败: {e}')

    def _daily_base(self, pipeline_date: str) -> int:
        # daily_cache 在 market_cache.db 分库（356号），必须走 sharding_manager
        try:
            conn = self._sm.get_connection(self._sm.get_db_for_table('daily_cache'))
            row = conn.execute(
                'SELECT COUNT(*) FROM daily_cache WHERE trade_date=?', [pipeline_date]
            ).fetchone()
            return row[0] if row else 0
        except Exception:
            return 0


# ── 组件 2：QualityChecker（423号 §2.3）──────────────────────────

class QualityChecker:
    """数据质量校验——按 QUALITY_RULES 动态覆盖率基准执行单表/跨表校验

    修正 v1.0：累积表按当日批次（trade_date）校验；覆盖率以 daily_cache 为锚。
    """

    def __init__(self, ecm=None):
        self._ecm = ecm
        self._sm = _resolve_sharding()

    def _count_by_date(self, table: str, pipeline_date: str) -> int:
        rule = QUALITY_RULES.get(table, {})
        date_col = rule.get('date_col', 'trade_date')
        distinct = rule.get('distinct_ts', False)
        count_expr = 'COUNT(DISTINCT ts_code)' if distinct else 'COUNT(*)'
        try:
            conn = self._sm.get_connection(self._sm.get_db_for_table(table))
            row = conn.execute(
                f'SELECT {count_expr} FROM {table} WHERE {date_col}=?', [pipeline_date]
            ).fetchone()
            return row[0] if row else 0
        except Exception as e:
            logger.warning(f'{table} 行数统计失败: {e}')
            return -1

    def daily_base(self, pipeline_date: str) -> int:
        """基准 N：daily_cache 目标日期行数（356号分库——daily_cache 在 market_cache.db）"""
        try:
            conn = self._sm.get_connection(self._sm.get_db_for_table('daily_cache'))
            row = conn.execute(
                'SELECT COUNT(*) FROM daily_cache WHERE trade_date=?', [pipeline_date]
            ).fetchone()
            return row[0] if row else 0
        except Exception:
            return 0

    def check_table(self, table: str, pipeline_date: str) -> CheckResult:
        """单表校验：行数覆盖率 + 必填字段 + JSON 字段"""
        rule = QUALITY_RULES.get(table)
        if rule is None:
            return CheckResult(True, table, pipeline_date, issues=[f'{table} 无校验规则，跳过'])
        n = self.daily_base(pipeline_date)
        actual = self._count_by_date(table, pipeline_date)
        if actual < 0:
            return CheckResult(False, table, pipeline_date,
                               issues=[f'{table} 统计失败（表可能不存在）'], severity='HIGH')
        threshold = int(n * rule.get('rows_ratio', 0.95))
        issues = []
        if n <= 0:
            issues.append('daily_cache 基准行数=0（数据未就绪）')
        elif actual < threshold:
            issues.append(f'{table} 覆盖率不足: {actual}/{threshold}（{actual/max(n,1):.0%} < {rule.get("rows_ratio", 0.95):.0%}）')

        # 必填字段非空抽查（当日前 200 行）
        required = rule.get('required_fields', [])
        if required and actual > 0 and not issues:
            bad = self._count_null_fields(table, pipeline_date, required)
            if bad > 0:
                issues.append(f'{table} 必填字段非空行 {bad} 条')
        severity = 'HIGH' if issues else 'LOW'
        return CheckResult(not issues, table, pipeline_date,
                           expected=threshold, actual=actual, issues=issues, severity=severity)

    def _count_null_fields(self, table: str, pipeline_date: str, fields: list) -> int:
        date_col = QUALITY_RULES.get(table, {}).get('date_col', 'trade_date')
        cond = ' OR '.join(f'({f} IS NULL OR {f}=\'\')' for f in fields)
        try:
            conn = self._sm.get_connection(self._sm.get_db_for_table(table))
            row = conn.execute(
                f'SELECT COUNT(*) FROM (SELECT * FROM {table} WHERE {date_col}=? LIMIT 200) '
                f'WHERE {cond}', [pipeline_date]
            ).fetchone()
            return row[0] if row else 0
        except Exception:
            return 0

    def check_cross_table(self, pipeline_date: str) -> list:
        """跨表对齐校验：indicator_* 与 daily_cache 行数差异 <5%（423号 §2.3）"""
        results: list[CheckResult] = []
        n = self.daily_base(pipeline_date)
        if n <= 0:
            return results
        for table in ['indicator_ma', 'indicator_macd', 'indicator_other']:
            actual = self._count_by_date(table, pipeline_date)
            if actual < 0:
                continue
            if actual < n * 0.95:
                results.append(CheckResult(
                    False, table, pipeline_date, expected=int(n * 0.95), actual=actual,
                    issues=[f'{table} 与 daily_cache 日期不对齐: daily={n}, {table}={actual}'],
                    severity='HIGH', kind='cross'))
        return results

    def check_pipeline_date(self, pipeline_date: str) -> list:
        """整日校验：全部规则表 + 跨表对齐（QA-CHECK 步骤主体）"""
        results = []
        for table in QUALITY_RULES:
            results.append(self.check_table(table, pipeline_date))
        results.extend(self.check_cross_table(pipeline_date))
        return results

    # ── G3：SIG 计算结果自检（signal_json/dim_results_json/seven_dim_json）──
    def validate_signal_rows(self, rows: list) -> list:
        """G3 专项：校验 SIG 批量写入行（索引 2/4/5），返回问题列表（空 = 通过）

        - signal_json / dim_results_json：可 json.loads 且非空
        - seven_dim_json：非空时须含 7 个 dim 键
        """
        issues = []
        for i, row in enumerate(rows):
            try:
                signal = json.loads(row[_SIG_ROW_IDX['signal_json']])
            except Exception:
                issues.append(f'第{i}行 signal_json 非法（ts_code={row[0]}）')
                continue
            if not signal:
                issues.append(f'第{i}行 signal_json 为空（ts_code={row[0]}）')
            try:
                json.loads(row[_SIG_ROW_IDX['dim_results_json']]) \
                    if row[_SIG_ROW_IDX['dim_results_json']] else {}
            except Exception:
                issues.append(f'第{i}行 dim_results_json 非法（ts_code={row[0]}）')
            sd = row[_SIG_ROW_IDX['seven_dim_json']]
            if sd:
                try:
                    sd_obj = json.loads(sd)
                    if not sd_obj:
                        issues.append(f'第{i}行 seven_dim_json 为空 dict（ts_code={row[0]}）')
                    else:
                        # seven_dim_json 条件性产出（仅 summary 恒有），校验必含 summary
                        for _req in QUALITY_RULES['strategy_signal_detail'].get('seven_dim_required', []):
                            if _req not in sd_obj:
                                issues.append(
                                    f'第{i}行 seven_dim_json 缺 {_req} 键（ts_code={row[0]}，实际键={list(sd_obj.keys())}）')
                except Exception:
                    issues.append(f'第{i}行 seven_dim_json 非法（ts_code={row[0]}）')
            if len(issues) > 20:
                issues.append(f'问题行数过多，停止扫描（共{i+1}行）')
                break
        return issues


# ── 组件 3：RecomputeScheduler（423号 §2.4）──────────────────────

# 问题关键字 → 责任步骤（executor 由 daemon 注入，见 schedule_recompute 参数）
# 注：daily_cache 缺失不映射 COL 步骤——COL-1..6 为"数据已完整跳过"模式且补采由
# run_integrity_check 独立负责（423号 §2.4 双通道边界），置 pending 无实际作用。
RECOMPUTE_KEYS = {
    'indicator_ma': 'RAW-1',
    'indicator_macd': 'RAW-1',
    'indicator_other': 'RAW-1',
    'pre_feat_cache': 'RAW-2',
    'factor_cache': 'RAW-3',
    'strategy_signal_detail': 'SIG',
    'status_snapshot': 'JUD',
    'treemap_snapshot': 'JUD',
}


class RecomputeScheduler:
    """数据问题→责任环节映射与调度（复用 pipeline_status 状态机）

    调度方式：将目标 step 置为 pending，由 _drive_pipeline 下个 tick 自动重跑
    （不新建执行通道；与 sync_requests 边界：本调度仅 daemon 侧管道内使用）。
    """

    def __init__(self, ecm=None):
        self._ecm = ecm

    def step_for_issue(self, issue: str) -> Optional[str]:
        for key, step in RECOMPUTE_KEYS.items():
            if key in issue:
                return step
        return None

    def schedule_recompute(self, issue: str, pipeline_date: str) -> bool:
        """根据问题类型调度对应环节补算（置 pending，管道自动重跑）"""
        step = self.step_for_issue(issue)
        if not step:
            logger.warning(f'无对应补算步骤: {issue}')
            return False
        ecm = _resolve_ecm(self._ecm)
        try:
            rc = ecm.conn.execute(
                "UPDATE pipeline_status SET status='pending', "
                "detail='QA触发补算: ' || ? WHERE pipeline_date=? AND step_id=? "
                "AND status='done'",
                [issue, pipeline_date, step]).rowcount
            ecm.conn.commit()
        except Exception as e:
            logger.warning(f'调度补算失败 {issue}→{step}: {e}')
            return False
        if rc > 0:
            logger.info(f'[QA] 触发补算: {issue} → {step}（{pipeline_date}）')
        else:
            logger.info(f'[QA] {step} 非 done 状态或不存在，跳过重置: {issue}')
        return True

    def issues_from_checks(self, check_results: list) -> list:
        """从校验结果中提取需要补算的问题列表"""
        issues = []
        for r in check_results:
            if r.passed:
                continue
            for issue in r.issues:
                # 剔除纯信息性问题（无对应补算步骤的保留原文由调用方处置）
                if self.step_for_issue(issue) or issue.startswith(r.table):
                    issues.append(issue)
        return issues


# ── 多轮核查（423号 §3，事件驱动；单轮执行体）──────────────────

def run_quality_round(pipeline_date: str, checker: QualityChecker,
                      scheduler: RecomputeScheduler, status_date: Optional[str] = None) -> dict:
    """单轮核查：校验 → 调度补算 → 返回汇总（事件驱动，非阻塞）

    pipeline_date：数据校验日期（trade_date 格式 'YYYY-MM-DD'，对齐各数据表）
    status_date：pipeline_status 表日期（compact 'YYYYMMDD'），默认同 pipeline_date；
                两者格式不同（数据表用 '-' 分隔，管道状态表用 compact），
                运行验证（423号）暴露格式不匹配致补算调度静默跳过。

    返回 {'passed': bool, 'results': [...], 'scheduled': [...]}
    """
    if status_date is None:
        status_date = pipeline_date
    results = checker.check_pipeline_date(pipeline_date)
    failed = [r for r in results if not r.passed]
    scheduled = []
    if failed:
        issues = scheduler.issues_from_checks(failed)
        for issue in issues:
            ok = scheduler.schedule_recompute(issue, status_date)
            if ok:
                scheduled.append(issue)
    return {
        'passed': not failed,
        'failed_count': len(failed),
        'results': [r.to_dict() for r in results],
        'scheduled': scheduled,
    }
