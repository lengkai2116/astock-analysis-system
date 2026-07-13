"""
风险维度 NLG 渲染器 — 风险等级、验证链 → 中文描述
"""

from .templates import RISK_LEVEL, CONSENSUS_LEVEL


def render_risk(risk_level: str, risk_notes: list = None) -> str:
    """渲染风险等级中文描述。

    Args:
        risk_level: LOW/MEDIUM/HIGH/CRITICAL
        risk_notes: 风险点列表

    Returns:
        中文风险描述（20-50 字）
    """
    risk_cn = RISK_LEVEL.get(risk_level, risk_level)
    parts = [f"风险等级 {risk_cn}"]

    if risk_notes:
        parts.extend(risk_notes[:2])

    return "，".join(parts) + "。" if parts else ""


def render_verification_chains(chains: list) -> str:
    """渲染验证链状态为中文描述。

    Args:
        chains: [{name, passed, reason}, ...]

    Returns:
        验证链中文描述
    """
    if not chains:
        return ""

    lines = []
    for chain in chains[:4]:
        name = chain.get("name", "验证链")
        passed = chain.get("passed", False)
        reason = chain.get("reason", "")
        status = "✅ 通过" if passed else "❌ 未通过"
        if reason:
            lines.append(f"  {name}: {status}（{reason}）")
        else:
            lines.append(f"  {name}: {status}")

    return "\n".join(lines) if lines else ""


def render_consensus(consensus_level: str) -> str:
    """渲染共识等级描述。"""
    cn = CONSENSUS_LEVEL.get(consensus_level, consensus_level)
    return f"各策略{cn}。"
