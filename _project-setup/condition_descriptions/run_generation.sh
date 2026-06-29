#!/bin/bash
# ============================================================
# 条件说明生成 — 一键运行脚本
# ============================================================
# 使用方法：
#   bash run_generation.sh
#
# 环境变量选项：
#   LLM_PROVIDER=lmstudio|deepseek    （可选，不设则交互式选择）
#   LMSTUDIO_BASE_URL=http://...      （可选，默认 http://192.168.3.1:1234）
#
# 前置要求：
#   1. LM Studio → 加载 Qwen3.5-9B → 启动 API 服务器
#   2. 确认 conditions_input.json 已编写完成
# ============================================================

set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$SCRIPT_DIR"

echo "========================================"
echo "  条件说明生成 — 一键运行"
echo "========================================"
echo ""

# 1. 检查 conditions_input.json
if [ ! -f "conditions_input.json" ]; then
    echo "❌ 未找到 conditions_input.json"
    echo "   请先编写条件清单文件"
    exit 1
fi

# 2. 检查 Python 3
if ! command -v python3 &> /dev/null; then
    echo "❌ 未找到 python3"
    exit 1
fi

# 3. 如果是 LM Studio 模式，先检查模型是否加载
if [ "$LLM_PROVIDER" = "lmstudio" ] || [ -z "$LLM_PROVIDER" ]; then
    echo "🔍 检查 LM Studio 连接..."
    curl -s -o /dev/null -w "%{http_code}" --max-time 5 \
        "${LMSTUDIO_BASE_URL:-http://192.168.3.1:1234}/v1/models" \
        2>/dev/null | grep -q "200" && echo "   ✅ LM Studio 已连接" || {
        echo "   ⚠️  LM Studio 未响应，将进入交互式选择"
        echo "      (也可设置 LLM_PROVIDER=deepseek 跳过此检查)"
    }
fi

echo ""
echo "🚀 开始生成条件说明..."
echo "   预估总时间: 约 2-3 分钟/条 × 条件数"
echo "   建议在终端后台运行: nohup bash run_generation.sh &"
echo ""

python3 generate_condition_descriptions.py

echo ""
echo "✅ 生成完成！"
echo "   结果文件: output/condition_descriptions.json"
echo "   日志文件: output/_generation_log.txt"
