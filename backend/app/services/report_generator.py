"""
报告生成器
支持多格式输出：Markdown、HTML、Jinja2模板
"""

import os
import json
from typing import Dict, List, Optional, Any
from datetime import datetime
from pathlib import Path
import logging

try:
    from jinja2 import Environment, FileSystemLoader, select_autoescape
    JINJA2_AVAILABLE = True
except ImportError:
    JINJA2_AVAILABLE = False
    logging.warning("Jinja2未安装，将使用简单模板")

logger = logging.getLogger(__name__)


class ReportGenerator:
    """
    报告生成器
    
    支持多种报告类型：
    - 单股票策略报告
    - 回测报告
    - 研究报告
    
    支持多种输出格式：
    - Markdown
    - HTML
    - JSON
    """
    
    def __init__(self, template_dir: Optional[str] = None):
        self.template_dir = template_dir or self._get_default_template_dir()
        self.jinja_env = None
        
        if JINJA2_AVAILABLE and os.path.exists(self.template_dir):
            try:
                self.jinja_env = Environment(
                    loader=FileSystemLoader(self.template_dir),
                    autoescape=select_autoescape(['html', 'xml'])
                )
            except Exception as e:
                logger.warning(f"Jinja2环境初始化失败: {str(e)}")
    
    def _get_default_template_dir(self) -> str:
        """获取默认模板目录"""
        current_dir = Path(__file__).parent
        template_dir = current_dir.parent.parent / 'templates'
        
        if not template_dir.exists():
            template_dir.mkdir(parents=True, exist_ok=True)
            self._create_default_templates(template_dir)
        
        return str(template_dir)
    
    def _create_default_templates(self, template_dir: Path):
        """创建默认模板"""
        template_dir.mkdir(parents=True, exist_ok=True)
        
        markdown_template = template_dir / 'report.md'
        if not markdown_template.exists():
            markdown_template.write_text(self._get_default_markdown_template(), encoding='utf-8')
        
        html_template = template_dir / 'report.html'
        if not html_template.exists():
            html_template.write_text(self._get_default_html_template(), encoding='utf-8')
    
    def _get_default_markdown_template(self) -> str:
        """获取默认Markdown模板"""
        return """# {{ title }}

**生成时间**: {{ generated_at }}
**股票代码**: {{ ts_code }}
**分析周期**: {{ start_date }} - {{ end_date }}

---

## 执行摘要

{{ summary }}

**总体评分**: {{ overall_score }}/100
**风险等级**: {{ risk_level }}

---

## 策略概述

**策略类型**: {{ strategy_type }}
**指标公式**: {{ formula }}

### 信号逻辑
{{ signal_logic }}

---

## 回测结果

### 收益指标
- **总收益率**: {{ total_return }}%
- **年化收益率**: {{ annual_return }}%
- **夏普比率**: {{ sharpe_ratio }}
- **索提诺比率**: {{ sortino_ratio }}

### 风险指标
- **最大回撤**: {{ max_drawdown }}%
- **波动率**: {{ volatility }}%
- **风险等级**: {{ risk_level }}

### 一致性指标
- **胜率**: {{ win_rate }}%
- **盈亏比**: {{ profit_loss_ratio }}
- **总交易次数**: {{ total_trades }}

---

## 优势分析

{% for strength in strengths %}
- {{ strength }}
{% endfor %}

---

## 劣势分析

{% for weakness in weaknesses %}
- {{ weakness }}
{% endfor %}

---

## 改进建议

{% for suggestion in suggestions %}
{{ loop.index }}. {{ suggestion }}
{% endfor %}

---

## 交易建议

### 适用对象
{{ suitable_for }}

### 仓位管理
{{ position_management }}

### 风险控制
{{ risk_control }}

### 下一步
{{ next_steps }}

---

## 详细数据

### 交易记录
{% if trades %}
| 日期 | 类型 | 价格 | 数量 | 收益率 |
|------|------|------|------|--------|
{% for trade in trades %}
| {{ trade.date }} | {{ trade.type }} | {{ trade.price }} | {{ trade.quantity }} | {{ trade.return }}% |
{% endfor %}
{% else %}
暂无交易记录
{% endif %}

---

### 每日权益曲线
{% if equity_curve %}
- 初始资金: {{ initial_capital }}
- 最终价值: {{ final_value }}
- 总收益: {{ total_pnl }}
{% else %}
暂无权益曲线数据
{% endif %}

---

## 附录

### 质量检查结果
- **检查通过**: {{ quality_passed }}
{% if quality_warnings %}
- **警告**: {{ quality_warnings }}
{% endif %}

### 执行信息
- **执行时长**: {{ execution_time }}秒
- **数据点数**: {{ data_points }}

---

*本报告由A股分析系统自动生成，仅供参考，不构成投资建议。*
"""
    
    def _get_default_html_template(self) -> str:
        """获取默认HTML模板"""
        return """<!DOCTYPE html>
<html lang="zh-CN">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>{{ title }}</title>
    <style>
        body {
            font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, "Helvetica Neue", Arial, sans-serif;
            max-width: 1200px;
            margin: 0 auto;
            padding: 20px;
            background: #f5f5f5;
            color: #333;
        }
        .report-container {
            background: white;
            border-radius: 12px;
            padding: 40px;
            box-shadow: 0 2px 8px rgba(0,0,0,0.1);
        }
        .header {
            border-bottom: 3px solid #3b82f6;
            padding-bottom: 20px;
            margin-bottom: 30px;
        }
        h1 { color: #1e293b; margin: 0 0 10px 0; }
        .meta { color: #64748b; font-size: 14px; }
        .summary-box {
            background: linear-gradient(135deg, #3b82f6 0%, #1d4ed8 100%);
            color: white;
            padding: 24px;
            border-radius: 8px;
            margin-bottom: 24px;
        }
        .score-badge {
            display: inline-block;
            background: rgba(255,255,255,0.2);
            padding: 8px 16px;
            border-radius: 20px;
            font-size: 24px;
            font-weight: bold;
        }
        .metrics-grid {
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(250px, 1fr));
            gap: 16px;
            margin: 24px 0;
        }
        .metric-card {
            background: #f8fafc;
            padding: 20px;
            border-radius: 8px;
            border-left: 4px solid #3b82f6;
        }
        .metric-title { color: #64748b; font-size: 14px; margin-bottom: 8px; }
        .metric-value { color: #1e293b; font-size: 24px; font-weight: bold; }
        .section {
            margin: 32px 0;
        }
        .section-title {
            color: #1e293b;
            font-size: 20px;
            font-weight: 600;
            margin-bottom: 16px;
            padding-bottom: 8px;
            border-bottom: 2px solid #e2e8f0;
        }
        .strength-item, .weakness-item {
            padding: 12px 16px;
            margin: 8px 0;
            border-radius: 6px;
        }
        .strength-item { background: #ecfdf5; color: #065f46; }
        .weakness-item { background: #fef2f2; color: #991b1b; }
        .advice-box {
            background: #fffbeb;
            border-left: 4px solid #f59e0b;
            padding: 20px;
            border-radius: 6px;
            margin: 16px 0;
        }
        table {
            width: 100%;
            border-collapse: collapse;
            margin: 16px 0;
        }
        th, td {
            padding: 12px;
            text-align: left;
            border-bottom: 1px solid #e2e8f0;
        }
        th { background: #f8fafc; font-weight: 600; color: #475569; }
        .footer {
            margin-top: 40px;
            padding-top: 20px;
            border-top: 1px solid #e2e8f0;
            text-align: center;
            color: #94a3b8;
            font-size: 12px;
        }
    </style>
</head>
<body>
    <div class="report-container">
        <div class="header">
            <h1>{{ title }}</h1>
            <div class="meta">
                生成时间: {{ generated_at }} | 
                股票代码: {{ ts_code }} | 
                周期: {{ start_date }} - {{ end_date }}
            </div>
        </div>
        
        <div class="summary-box">
            <div>{{ summary }}</div>
            <div style="margin-top: 16px;">
                <span class="score-badge">评分: {{ overall_score }}/100</span>
                <span style="margin-left: 20px;">风险等级: {{ risk_level }}</span>
            </div>
        </div>
        
        <div class="section">
            <h2 class="section-title">策略概述</h2>
            <p><strong>策略类型:</strong> {{ strategy_type }}</p>
            <p><strong>指标公式:</strong> <code>{{ formula }}</code></p>
            <div class="advice-box">
                <strong>信号逻辑:</strong><br>
                {{ signal_logic }}
            </div>
        </div>
        
        <div class="section">
            <h2 class="section-title">回测结果</h2>
            <div class="metrics-grid">
                <div class="metric-card">
                    <div class="metric-title">总收益率</div>
                    <div class="metric-value">{{ total_return }}%</div>
                </div>
                <div class="metric-card">
                    <div class="metric-title">年化收益率</div>
                    <div class="metric-value">{{ annual_return }}%</div>
                </div>
                <div class="metric-card">
                    <div class="metric-title">夏普比率</div>
                    <div class="metric-value">{{ sharpe_ratio }}</div>
                </div>
                <div class="metric-card">
                    <div class="metric-title">最大回撤</div>
                    <div class="metric-value">{{ max_drawdown }}%</div>
                </div>
                <div class="metric-card">
                    <div class="metric-title">胜率</div>
                    <div class="metric-value">{{ win_rate }}%</div>
                </div>
                <div class="metric-card">
                    <div class="metric-title">总交易次数</div>
                    <div class="metric-value">{{ total_trades }}</div>
                </div>
            </div>
        </div>
        
        {% if strengths %}
        <div class="section">
            <h2 class="section-title">优势分析</h2>
            {% for strength in strengths %}
            <div class="strength-item">✓ {{ strength }}</div>
            {% endfor %}
        </div>
        {% endif %}
        
        {% if weaknesses %}
        <div class="section">
            <h2 class="section-title">劣势分析</h2>
            {% for weakness in weaknesses %}
            <div class="weakness-item">✗ {{ weakness }}</div>
            {% endfor %}
        </div>
        {% endif %}
        
        {% if suggestions %}
        <div class="section">
            <h2 class="section-title">改进建议</h2>
            <ol>
            {% for suggestion in suggestions %}
                <li>{{ suggestion }}</li>
            {% endfor %}
            </ol>
        </div>
        {% endif %}
        
        <div class="section">
            <h2 class="section-title">交易建议</h2>
            <div class="advice-box">
                <p><strong>适用对象:</strong> {{ suitable_for }}</p>
                <p><strong>仓位管理:</strong> {{ position_management }}</p>
                <p><strong>风险控制:</strong> {{ risk_control }}</p>
                <p><strong>下一步:</strong> {{ next_steps }}</p>
            </div>
        </div>
        
        <div class="footer">
            <p>本报告由A股分析系统自动生成，仅供参考，不构成投资建议。</p>
            <p>生成时间: {{ generated_at }}</p>
        </div>
    </div>
</body>
</html>
"""
    
    def generate_single_stock_report(self, stock_data: Dict, 
                                    strategy_data: Dict,
                                    format: str = 'markdown') -> str:
        """
        生成单股票策略报告
        
        Args:
            stock_data: 股票数据
            strategy_data: 策略数据
            format: 输出格式 ('markdown', 'html', 'json')
        
        Returns:
            生成的报告内容
        """
        logger.info(f"生成单股票策略报告，格式: {format}")
        
        report_data = {
            'title': f"{stock_data.get('name', '未知股票')} ({stock_data.get('ts_code', '')}) 策略分析报告",
            'generated_at': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
            'ts_code': stock_data.get('ts_code', ''),
            'stock_name': stock_data.get('name', ''),
            'start_date': stock_data.get('start_date', ''),
            'end_date': stock_data.get('end_date', ''),
            'strategy_type': strategy_data.get('indicator_type', ''),
            'formula': strategy_data.get('formula', ''),
            'signal_logic': strategy_data.get('signal', ''),
            'description': strategy_data.get('description', '')
        }
        
        report_data.update(self._format_metrics(strategy_data.get('metrics', {})))
        
        if format == 'json':
            return json.dumps(report_data, ensure_ascii=False, indent=2)
        elif format == 'html':
            return self._render_html_template(report_data)
        else:
            return self._render_markdown_template(report_data)
    
    def generate_backtest_report(self, backtest_result: Dict,
                                interpretation: Optional[Dict] = None,
                                format: str = 'markdown') -> str:
        """
        生成回测报告
        
        Args:
            backtest_result: 回测结果
            interpretation: AI解读结果（可选）
            format: 输出格式 ('markdown', 'html', 'json')
        
        Returns:
            生成的报告内容
        """
        logger.info(f"生成回测报告，格式: {format}")
        
        metrics = backtest_result.get('metrics', {})
        
        report_data = {
            'title': '量化策略回测报告',
            'generated_at': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
            'ts_code': backtest_result.get('ts_code', '未知'),
            'start_date': backtest_result.get('start_date', ''),
            'end_date': backtest_result.get('end_date', ''),
            'initial_capital': metrics.get('initial_capital', 0),
            'final_value': metrics.get('final_value', 0),
            'trades': backtest_result.get('trades', []),
            'equity_curve': backtest_result.get('daily_equity', [])
        }
        
        report_data.update(self._format_metrics(metrics))
        
        if interpretation:
            report_data.update({
                'overall_score': interpretation.get('overall_score', 0),
                'risk_level': interpretation.get('risk_level', '未知'),
                'summary': interpretation.get('summary', ''),
                'strengths': interpretation.get('strengths', []),
                'weaknesses': interpretation.get('weaknesses', []),
                'suggestions': interpretation.get('suggestions', []),
                'trading_advice': interpretation.get('trading_advice', {})
            })
            
            advice = interpretation.get('trading_advice', {})
            report_data.update({
                'suitable_for': advice.get('suitable_for', ''),
                'position_management': advice.get('position_management', ''),
                'risk_control': advice.get('risk_control', ''),
                'next_steps': advice.get('next_steps', '')
            })
        
        if format == 'json':
            return json.dumps(report_data, ensure_ascii=False, indent=2)
        elif format == 'html':
            return self._render_html_template(report_data)
        else:
            return self._render_markdown_template(report_data)
    
    def generate_research_report(self, pipeline_context: Dict,
                                format: str = 'markdown') -> Dict[str, Any]:
        """
        生成完整的研究报告
        
        Args:
            pipeline_context: 流水线上下文
            format: 输出格式
        
        Returns:
            报告数据字典
        """
        logger.info("生成完整研究报告")
        
        validated_input = pipeline_context.get('validated_input', {})
        generated_strategy = pipeline_context.get('generated_strategy', {})
        backtest_result = pipeline_context.get('backtest_result', {})
        interpretation = pipeline_context.get('interpretation', {})
        
        sections = []
        
        sections.append({
            'title': '研究概述',
            'content': f"本报告基于用户描述「{validated_input.get('description', '')}」生成的分析报告。",
            'level': 1
        })
        
        sections.append({
            'title': '策略详情',
            'content': generated_strategy.get('description', ''),
            'details': {
                '指标类型': generated_strategy.get('indicator_type', ''),
                '计算公式': generated_strategy.get('formula', ''),
                '信号逻辑': generated_strategy.get('signal', '')
            },
            'level': 2
        })
        
        if backtest_result:
            metrics = backtest_result.get('metrics', {})
            sections.append({
                'title': '回测结果',
                'metrics': {
                    '总收益率': f"{metrics.get('total_return', 0)*100:.2f}%",
                    '年化收益率': f"{metrics.get('annual_return', 0)*100:.2f}%",
                    '夏普比率': f"{metrics.get('sharpe_ratio', 0):.2f}",
                    '最大回撤': f"{metrics.get('max_drawdown', 0)*100:.2f}%",
                    '胜率': f"{metrics.get('win_rate', 0)*100:.1f}%"
                },
                'level': 2
            })
        
        if interpretation:
            sections.append({
                'title': 'AI分析',
                'summary': interpretation.get('summary', ''),
                'score': interpretation.get('overall_score', 0),
                'risk_level': interpretation.get('risk_level', ''),
                'strengths': interpretation.get('strengths', []),
                'weaknesses': interpretation.get('weaknesses', []),
                'suggestions': interpretation.get('suggestions', []),
                'level': 2
            })
        
        report = {
            'title': '量化研究分析报告',
            'generated_at': datetime.now().isoformat(),
            'ts_code': validated_input.get('ts_code', ''),
            'start_date': validated_input.get('start_date', ''),
            'end_date': validated_input.get('end_date', ''),
            'sections': sections,
            'metadata': {
                'pipeline_id': pipeline_context.get('pipeline_id', ''),
                'quality_check': pipeline_context.get('quality_check', {}),
                'execution_result': pipeline_context.get('execution_result', {})
            }
        }
        
        if format in ['markdown', 'html']:
            report['content'] = self._generate_markdown_from_sections(sections) if format == 'markdown' else self._generate_html_from_sections(sections)
        
        logger.info(f"研究报告生成完成，包含 {len(sections)} 个章节")
        
        return report
    
    def _format_metrics(self, metrics: Dict) -> Dict:
        """格式化指标数据"""
        return {
            'total_return': f"{metrics.get('total_return', 0)*100:.2f}",
            'annual_return': f"{metrics.get('annual_return', 0)*100:.2f}",
            'sharpe_ratio': f"{metrics.get('sharpe_ratio', 0):.2f}",
            'sortino_ratio': f"{metrics.get('sortino_ratio', 0):.2f}",
            'max_drawdown': f"{metrics.get('max_drawdown', 0)*100:.2f}",
            'volatility': f"{metrics.get('volatility', 0)*100:.2f}",
            'win_rate': f"{metrics.get('win_rate', 0)*100:.1f}",
            'profit_loss_ratio': f"{metrics.get('profit_loss_ratio', 0):.2f}",
            'total_trades': metrics.get('total_trades', 0)
        }
    
    def _render_markdown_template(self, data: Dict) -> str:
        """渲染Markdown模板"""
        if self.jinja_env:
            try:
                template = self.jinja_env.get_template('report.md')
                return template.render(**data)
            except Exception as e:
                logger.warning(f"模板渲染失败: {str(e)}")
        
        return self._generate_simple_markdown(data)
    
    def _render_html_template(self, data: Dict) -> str:
        """渲染HTML模板"""
        if self.jinja_env:
            try:
                template = self.jinja_env.get_template('report.html')
                return template.render(**data)
            except Exception as e:
                logger.warning(f"模板渲染失败: {str(e)}")
        
        return self._generate_simple_html(data)
    
    def _generate_simple_markdown(self, data: Dict) -> str:
        """生成简单的Markdown报告"""
        md = f"""# {data.get('title', '分析报告')}

**生成时间**: {data.get('generated_at', '')}  
**股票代码**: {data.get('ts_code', '')}  
**分析周期**: {data.get('start_date', '')} - {data.get('end_date', '')}

---

## 策略概述

**策略类型**: {data.get('strategy_type', '')}  
**指标公式**: `{data.get('formula', '')}`  
**信号逻辑**: {data.get('signal_logic', '')}

---

## 回测结果

- **总收益率**: {data.get('total_return', '0')}%
- **年化收益率**: {data.get('annual_return', '0')}%
- **夏普比率**: {data.get('sharpe_ratio', '0')}
- **最大回撤**: {data.get('max_drawdown', '0')}%
- **胜率**: {data.get('win_rate', '0')}%
- **总交易次数**: {data.get('total_trades', '0')}

"""
        
        if data.get('strengths'):
            md += "\n## 优势分析\n\n"
            for strength in data['strengths']:
                md += f"- {strength}\n"
        
        if data.get('weaknesses'):
            md += "\n## 劣势分析\n\n"
            for weakness in data['weaknesses']:
                md += f"- {weakness}\n"
        
        if data.get('suggestions'):
            md += "\n## 改进建议\n\n"
            for i, suggestion in enumerate(data['suggestions'], 1):
                md += f"{i}. {suggestion}\n"
        
        if data.get('suitable_for'):
            md += f"\n## 交易建议\n\n"
            md += f"- **适用对象**: {data['suitable_for']}\n"
            md += f"- **仓位管理**: {data.get('position_management', '')}\n"
            md += f"- **风险控制**: {data.get('risk_control', '')}\n"
            md += f"- **下一步**: {data.get('next_steps', '')}\n"
        
        md += "\n---\n\n*本报告由A股分析系统自动生成，仅供参考，不构成投资建议。*\n"
        
        return md
    
    def _generate_simple_html(self, data: Dict) -> str:
        """生成简单的HTML报告"""
        html = f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
    <meta charset="UTF-8">
    <title>{data.get('title', '分析报告')}</title>
    <style>
        body {{ font-family: Arial, sans-serif; max-width: 1000px; margin: 0 auto; padding: 20px; }}
        .header {{ border-bottom: 3px solid #3b82f6; padding-bottom: 20px; margin-bottom: 30px; }}
        h1 {{ color: #1e293b; }}
        .meta {{ color: #64748b; font-size: 14px; }}
        .metrics {{ display: grid; grid-template-columns: repeat(3, 1fr); gap: 16px; margin: 20px 0; }}
        .metric {{ background: #f8fafc; padding: 16px; border-radius: 8px; }}
        .metric-title {{ color: #64748b; font-size: 14px; }}
        .metric-value {{ color: #1e293b; font-size: 24px; font-weight: bold; }}
        .strength {{ background: #ecfdf5; color: #065f46; padding: 12px; margin: 8px 0; border-radius: 6px; }}
        .weakness {{ background: #fef2f2; color: #991b1b; padding: 12px; margin: 8px 0; border-radius: 6px; }}
    </style>
</head>
<body>
    <div class="header">
        <h1>{data.get('title', '分析报告')}</h1>
        <div class="meta">生成时间: {data.get('generated_at', '')} | 股票: {data.get('ts_code', '')}</div>
    </div>
    
    <h2>策略概述</h2>
    <p><strong>类型:</strong> {data.get('strategy_type', '')} | <strong>公式:</strong> <code>{data.get('formula', '')}</code></p>
    
    <h2>回测结果</h2>
    <div class="metrics">
        <div class="metric"><div class="metric-title">总收益率</div><div class="metric-value">{data.get('total_return', '0')}%</div></div>
        <div class="metric"><div class="metric-title">夏普比率</div><div class="metric-value">{data.get('sharpe_ratio', '0')}</div></div>
        <div class="metric"><div class="metric-title">最大回撤</div><div class="metric-value">{data.get('max_drawdown', '0')}%</div></div>
    </div>
"""
        
        if data.get('strengths'):
            html += "<h2>优势分析</h2>"
            for strength in data['strengths']:
                html += f'<div class="strength">✓ {strength}</div>\n'
        
        if data.get('weaknesses'):
            html += "<h2>劣势分析</h2>"
            for weakness in data['weaknesses']:
                html += f'<div class="weakness">✗ {weakness}</div>\n'
        
        html += """
</body>
</html>
"""
        
        return html
    
    def _generate_markdown_from_sections(self, sections: List[Dict]) -> str:
        """从章节列表生成Markdown"""
        md = ""
        
        for section in sections:
            level = section.get('level', 1)
            md += f"{'#' * level} {section['title']}\n\n"
            
            if section.get('content'):
                md += f"{section['content']}\n\n"
            
            if section.get('details'):
                for key, value in section['details'].items():
                    md += f"- **{key}**: {value}\n"
                md += "\n"
            
            if section.get('metrics'):
                for key, value in section['metrics'].items():
                    md += f"- **{key}**: {value}\n"
                md += "\n"
            
            if section.get('strengths'):
                md += "**优势:**\n"
                for item in section['strengths']:
                    md += f"- {item}\n"
                md += "\n"
            
            if section.get('weaknesses'):
                md += "**劣势:**\n"
                for item in section['weaknesses']:
                    md += f"- {item}\n"
                md += "\n"
            
            if section.get('suggestions'):
                md += "**建议:**\n"
                for i, item in enumerate(section['suggestions'], 1):
                    md += f"{i}. {item}\n"
                md += "\n"
        
        return md
    
    def _generate_html_from_sections(self, sections: List[Dict]) -> str:
        """从章节列表生成HTML"""
        html = '<div class="report-sections">\n'
        
        for section in sections:
            level = section.get('level', 1)
            html += f'<h{level} class="section-title">{section["title"]}</h{level}>\n'
            
            if section.get('content'):
                html += f'<p>{section["content"]}</p>\n'
            
            if section.get('summary'):
                html += f'<div class="summary">{section["summary"]}</div>\n'
            
            if section.get('metrics'):
                html += '<div class="metrics-grid">\n'
                for key, value in section['metrics'].items():
                    html += f'<div class="metric"><div class="metric-title">{key}</div><div class="metric-value">{value}</div></div>\n'
                html += '</div>\n'
            
            if section.get('strengths'):
                html += '<div class="strengths">\n'
                for item in section['strengths']:
                    html += f'<div class="strength-item">✓ {item}</div>\n'
                html += '</div>\n'
            
            if section.get('suggestions'):
                html += '<ol class="suggestions">\n'
                for item in section['suggestions']:
                    html += f'<li>{item}</li>\n'
                html += '</ol>\n'
        
        html += '</div>\n'
        
        return html
    
    def save_report(self, content: str, filename: str, 
                   output_dir: Optional[str] = None) -> str:
        """
        保存报告到文件
        
        Args:
            content: 报告内容
            filename: 文件名
            output_dir: 输出目录（可选）
        
        Returns:
            保存的文件路径
        """
        if not output_dir:
            output_dir = Path.home() / 'astock_reports'
        
        output_path = Path(output_dir)
        output_path.mkdir(parents=True, exist_ok=True)
        
        file_path = output_path / filename
        
        with open(file_path, 'w', encoding='utf-8') as f:
            f.write(content)
        
        logger.info(f"报告已保存: {file_path}")
        
        return str(file_path)


def create_report_generator(config: Optional[Dict] = None) -> ReportGenerator:
    """创建报告生成器实例"""
    template_dir = config.get('template_dir') if config else None
    return ReportGenerator(template_dir)
