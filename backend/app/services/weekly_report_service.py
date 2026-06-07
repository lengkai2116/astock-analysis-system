"""
周度策略验证报告生成服务 — P2.7

功能：
  1. 汇总本周全部 SignalRecord（轨A） + VirtualPosition（轨B）验证结果
  2. 按信号类型分组计算胜率/收益统计
  3. 调用 DeepSeek AI 进行策略分析（可选）
  4. 生成 Markdown 格式周报
  5. 存档到 DATA_DIR/reports/周报-YYYY-MM-DD.md
  6. API 下载接口 GET /api/v1/reports/weekly

定时任务入口：scheduler.py → run_weekly_report()
"""
import os
import logging
from typing import Dict, List, Optional
from datetime import date, timedelta, datetime

from app import db
from app.models.verification import SignalRecord, VirtualPosition

logger = logging.getLogger(__name__)


class WeeklyReportService:
    """周度策略验证报告生成服务"""

    def __init__(self):
        self._data_dir = self._resolve_data_dir()

    @staticmethod
    @staticmethod
    def _resolve_data_dir() -> str:
        """从配置解析数据目录，报告存入 <DATA_DIR>/reports/"""
        from app.config import Config
        base = os.environ.get("DATA_DIR") or getattr(Config, "DATA_DIR", "/data")
        report_dir = os.path.join(base, "reports")
        os.makedirs(report_dir, exist_ok=True)
        return report_dir

    def _report_dir(self) -> str:
        return self._data_dir

    # ─────────────────────────────────────────────
    # 数据采集
    # ─────────────────────────────────────────────

    def _collect_weekly_data(self) -> dict:
        """查询本周的验证数据"""
        today = date.today()
        period_start = today - timedelta(days=7)

        signal_records = SignalRecord.query.filter(
            SignalRecord.signal_date >= period_start,
            SignalRecord.signal_date <= today,
        ).order_by(SignalRecord.signal_date.desc()).all()

        vps = VirtualPosition.query.filter(
            VirtualPosition.start_date >= period_start,
            VirtualPosition.start_date <= today,
        ).order_by(VirtualPosition.start_date.desc()).all()

        return {
            'signal_records': signal_records,
            'virtual_positions': vps,
            'period_start': period_start,
            'period_end': today,
        }

    # ─────────────────────────────────────────────
    # 统计计算
    # ─────────────────────────────────────────────

    def _compute_signal_stats(self, records: List[SignalRecord]) -> List[Dict]:
        """按信号类型分组汇总统计"""
        groups: Dict[str, dict] = {}

        for rec in records:
            st = rec.signal_type or 'UNKNOWN'
            if st not in groups:
                groups[st] = {
                    'signal_type': st,
                    'samples': 0,
                    'samples_t5': 0,
                    'samples_t10': 0,
                    'samples_t20': 0,
                    'wins_5d': 0,
                    'wins_10d': 0,
                    'wins_20d': 0,
                    'returns_20d': [],
                }
            g = groups[st]
            g['samples'] += 1
            if rec.return_t5 is not None:
                g['samples_t5'] += 1
                if rec.is_win_5d:
                    g['wins_5d'] += 1
            if rec.return_t10 is not None:
                g['samples_t10'] += 1
                if rec.is_win_10d:
                    g['wins_10d'] += 1
            if rec.return_t20 is not None:
                g['samples_t20'] += 1
                if rec.is_win_20d:
                    g['wins_20d'] += 1
                g['returns_20d'].append(rec.return_t20)

        result = []
        for st, g in sorted(groups.items()):
            import numpy as np
            avg_ret_20d = float(np.mean(g['returns_20d'])) if g['returns_20d'] else 0.0
            result.append({
                'signal_type': st,
                'samples': g['samples'],
                'win_rate_5d': round(g['wins_5d'] / max(g['samples_t5'], 1), 4),
                'win_rate_10d': round(g['wins_10d'] / max(g['samples_t10'], 1), 4),
                'win_rate_20d': round(g['wins_20d'] / max(g['samples_t20'], 1), 4),
                'avg_return_20d': round(avg_ret_20d, 4),
            })
        return result

    # ─────────────────────────────────────────────
    # AI 分析调用
    # ─────────────────────────────────────────────

    def _call_ai_analysis(self, stats: List[Dict], overview: dict) -> str:
        """调用 DeepSeek（或 Mock）对策略表现做分析"""
        from app.config import Config
        cfg = Config.get_llm_config()
        provider = cfg.get('type', 'mock')

        stat_lines = []
        for s in stats:
            stat_lines.append(
                f"  - {s['signal_type']}: 样本{s['samples']}条, "
                f"5日胜率{s['win_rate_5d']:.1%}, "
                f"20日胜率{s['win_rate_20d']:.1%}, "
                f"20日平均收益{s['avg_return_20d']:.2%}"
            )

        prompt = (
            "以下是一周策略虚拟验证数据，请分析策略表现、识别异常模式、提供优化方向建议。"
            "仅作分析，不修改策略。\n\n"
            f"## 本周验证概况\n"
            f"信号总数: {overview['total_signals']}条 (轨A:{overview['track_a']}, 轨B:{overview['track_b']})\n"
            f"覆盖股票: {overview['unique_stocks']}只\n"
            f"已完成T+5验证: {overview['completed_t5']}条 / "
            f"T+10: {overview['completed_t10']}条 / T+20: {overview['completed_t20']}条\n\n"
            f"## 各信号类型统计\n" + "\n".join(stat_lines)
        )

        if provider == 'deepseek':
            try:
                import requests
                api_key = cfg.get('api_key', '')
                endpoint = cfg.get('endpoint', 'https://api.deepseek.com/v1')
                model = cfg.get('model', 'deepseek-chat-v4')
                resp = requests.post(
                    f"{endpoint.rstrip('/')}/chat/completions",
                    headers={'Authorization': f'Bearer {api_key}', 'Content-Type': 'application/json'},
                    json={
                        'model': model,
                        'messages': [
                            {'role': 'system', 'content': '你是一名量化策略分析师，负责分析策略回测验证数据并提供改进建议。请用中文回答。'},
                            {'role': 'user', 'content': prompt},
                        ],
                        'temperature': 0.3,
                        'max_tokens': 1500,
                    },
                    timeout=30,
                )
                if resp.status_code == 200:
                    data = resp.json()
                    return data.get('choices', [{}])[0].get('message', {}).get('content', '')
                logger.warning(f"DeepSeek AI 调用失败: {resp.status_code}")
            except Exception as e:
                logger.warning(f"DeepSeek AI 调用异常: {e}")
        else:
            # Mock 模式
            if not stats:
                return "本周无足够的已验证信号，无法进行有意义的 AI 分析。"
            lines = [
                "### 总体表现评价",
                f"本周共 {overview['total_signals']} 条信号，覆盖 {overview['unique_stocks']} 只股票。",
            ]
            best = max(stats, key=lambda s: s['win_rate_20d']) if stats else None
            worst = min(stats, key=lambda s: s['win_rate_20d']) if stats else None
            if best:
                lines.append(f"表现最佳信号类型: {best['signal_type']} (20日胜率{best['win_rate_20d']:.1%})")
            if worst:
                lines.append(f"表现最弱信号类型: {worst['signal_type']} (20日胜率{worst['win_rate_20d']:.1%})")
            lines.append("")
            lines.append("### 风险提示")
            lines.append("以上为 Mock 模式分析结果。配置 DeepSeek API Key 后自动启用 AI 深度分析。")
            return "\n".join(lines)

        return ""

    # ─────────────────────────────────────────────
    # 报告生成
    # ─────────────────────────────────────────────

    def generate_weekly_report(self) -> Optional[str]:
        """生成周度策略验证报告"""
        try:
            data = self._collect_weekly_data()
            signals = data['signal_records']
            vps = data['virtual_positions']
            period_start = data['period_start']
            period_end = data['period_end']

            if not signals and not vps:
                logger.info("本周无信号或验证数据，跳过周报生成")
                return None

            # 统计概览
            ts_codes = set()
            completed_t5 = completed_t10 = completed_t20 = 0
            for r in signals:
                ts_codes.add(r.ts_code)
                if r.price_t5 is not None:
                    completed_t5 += 1
                if r.price_t10 is not None:
                    completed_t10 += 1
                if r.verification_status == 'completed':
                    completed_t20 += 1

            track_b_completed = sum(1 for v in vps if v.status == 'completed')

            overview = {
                'total_signals': len(signals),
                'track_a': len(signals),
                'track_b': len(vps),
                'unique_stocks': len(ts_codes),
                'completed_t5': completed_t5,
                'completed_t10': completed_t10,
                'completed_t20': completed_t20,
                'track_b_completed': track_b_completed,
            }

            # 信号类型统计
            stats = self._compute_signal_stats(signals)

            # AI 分析
            ai_analysis = self._call_ai_analysis(stats, overview)

            # 当前周数
            today = date.today()
            week_number = today.isocalendar()[1]

            # 组装 Markdown
            lines = [
                f"# 策略虚拟验证周报 — {today.year}年第{week_number}周",
                "",
                f"> 报告周期: {period_start.isoformat()} ~ {period_end.isoformat()}",
                f"> 生成时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
                "",
                "---",
                "",
                "## 一、本周验证概况",
                "",
                f"- 信号总数: {overview['total_signals']}条 (轨A:{overview['track_a']}, 轨B:{overview['track_b']})",
                f"- 覆盖股票: {overview['unique_stocks']}只",
                f"- 已完成T+5验证: {overview['completed_t5']}条",
                f"- 已完成T+10验证: {overview['completed_t10']}条",
                f"- 已完成T+20验证: {overview['completed_t20']}条",
                f"- 轨B虚拟验证已完成: {overview['track_b_completed']}条",
                "",
            ]

            if stats:
                lines += [
                    "## 二、各信号类型胜率",
                    "",
                    "| 信号类型 | 样本量 | win_5d | win_10d | win_20d | avg_return_20d |",
                    "|----------|--------|--------|---------|---------|----------------|",
                ]
                for s in stats:
                    lines.append(
                        f"| {s['signal_type']} | {s['samples']} | "
                        f"{s['win_rate_5d']:.1%} | {s['win_rate_10d']:.1%} | "
                        f"{s['win_rate_20d']:.1%} | {s['avg_return_20d']:.2%} |"
                    )
                lines.append("")

            # 轨A 详情
            if signals:
                lines += [
                    "### 轨A SignalRecord 详情",
                    "",
                    "| ID | 股票 | 信号日 | 策略 | 类型 | 状态 | T+5收益 | T+20收益 |",
                    "|----|------|--------|------|------|------|---------|---------|",
                ]
                for r in signals[:30]:
                    ret5 = f"{r.return_t5:.2%}" if r.return_t5 is not None else "-"
                    ret20 = f"{r.return_t20:.2%}" if r.return_t20 is not None else "-"
                    lines.append(
                        f"| {r.id} | {r.ts_code} | {r.signal_date} | "
                        f"{r.strategy_name} | {r.signal_type} | {r.verification_status} | "
                        f"{ret5} | {ret20} |"
                    )
                lines.append("")

            # 轨B 详情
            if vps:
                lines += [
                    "### 轨B 虚拟验证详情",
                    "",
                    "| ID | 股票 | 方向 | 入场 | 状态 | T+5收益 | T+20收益 | 判定 |",
                    "|----|------|------|------|------|---------|---------|------|",
                ]
                for vp in vps:
                    ret5 = f"{vp.return_t5:.2%}" if vp.return_t5 is not None else "-"
                    ret20 = f"{vp.return_t20:.2%}" if vp.return_t20 is not None else "-"
                    judgement = vp.final_judgement or "追踪中"
                    entry = f"{vp.entry_price:.2f}" if vp.entry_price else "-"
                    lines.append(
                        f"| {vp.id} | {vp.ts_code} | {vp.suggestion} | {entry} | "
                        f"{vp.status} | {ret5} | {ret20} | {judgement} |"
                    )
                lines.append("")

            # AI 分析
            lines += [
                "---",
                "",
                "## 三、AI 分析",
                "",
                ai_analysis if ai_analysis else "（AI 分析未启用，请配置 DeepSeek API Key）",
                "",
                "---",
                "",
                "## 四、优化建议方向",
                "",
                "> 以下为基于当前验证数据的初步观察，仅供 Codex 在人工判断时参考。",
                "",
            ]

            if stats:
                for s in stats:
                    if s['win_rate_5d'] < 0.45:
                        lines.append(f"- ⚠ {s['signal_type']} 5日胜率({s['win_rate_5d']:.1%})偏低，建议检查入场时机")
                    if s['win_rate_20d'] < 0.40:
                        lines.append(f"- ⚠ {s['signal_type']} 20日胜率({s['win_rate_20d']:.1%})偏低，可能需调整止盈止损范围")
                    if s['avg_return_20d'] < -0.02:
                        lines.append(f"- ⚠ {s['signal_type']} 20日平均收益({s['avg_return_20d']:.2%})为负，策略可能存在系统性偏差")
                    if s['samples'] < 5:
                        lines.append(f"- ℹ {s['signal_type']} 样本量({s['samples']}条)不足，结论置信度较低")

            if not stats:
                lines.append("- 本周验证数据不足，无法生成有效优化建议。")

            lines.extend(["", "---", "*本报告由 A股分析系统自动生成*"])

            content = "\n".join(lines)

            # 写入文件
            report_dir = self._report_dir()
            filepath = os.path.join(report_dir, f"周报-{today.isoformat()}.md")

            with open(filepath, 'w', encoding='utf-8') as f:
                f.write(content)

            logger.info(f"周度报告已生成: {filepath}")
            return filepath

        except Exception as e:
            logger.error(f"周度报告生成失败: {e}", exc_info=True)
            return None

    def list_recent_reports(self, limit: int = 10) -> List[str]:
        """列出最近生成的周报文件"""
        report_dir = self._report_dir()
        if not os.path.isdir(report_dir):
            return []
        files = sorted(
            [f for f in os.listdir(report_dir) if f.startswith("周报-") and f.endswith(".md")],
            reverse=True,
        )
        return [os.path.join(report_dir, f) for f in files[:limit]]

    def read_report(self, filepath: str) -> Optional[str]:
        """读取报告内容"""
        try:
            with open(filepath, 'r', encoding='utf-8') as f:
                return f.read()
        except Exception as e:
            logger.warning(f"读取报告失败 {filepath}: {e}")
            return None
