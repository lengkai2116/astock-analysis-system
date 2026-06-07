# {{ title }}

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
