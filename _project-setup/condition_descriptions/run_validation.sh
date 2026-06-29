#!/bin/bash
# ============================================================
# 条件说明质量验证脚本
# 快速验证 output/condition_descriptions.json 的完整性
# ============================================================

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
OUTPUT_FILE="$SCRIPT_DIR/output/condition_descriptions.json"

echo "========================================"
echo "  条件说明 — 质量验证"
echo "========================================"
echo ""

if [ ! -f "$OUTPUT_FILE" ]; then
    echo "❌ 未找到输出文件: $OUTPUT_FILE"
    echo "   请先运行 run_generation.sh"
    exit 1
fi

# 统计
TOTAL=$(python3 -c "import json; d=json.load(open('$OUTPUT_FILE')); print(len(d))")
echo "📊 总条件数: $TOTAL"

# 检查必填字段
echo ""
echo "🔍 字段完整性检查:"
REQUIRED_FIELDS="user_description how_it_works when_to_use when_not_to_use example"

python3 -c "
import json
d = json.load(open('$OUTPUT_FILE'))
fields = ['user_description', 'how_it_works', 'when_to_use', 'when_not_to_use', 'example']
for cid, data in d.items():
    for f in fields:
        if f not in data or not data[f]:
            print(f'  ⚠️ {cid}: 缺少 {f}')
print('  ✅ 所有条件基本字段检查完成')
"

# 检查知识库回退（没有关联参考的）
echo ""
echo "🔍 检查示例合理性（含股票和年份信息）:"
python3 -c "
import json
d = json.load(open('$OUTPUT_FILE'))
has_example = sum(1 for v in d.values() if 'example' in v and len(str(v['example'])) > 20)
no_example = sum(1 for v in d.values() if 'example' not in v or len(str(v.get('example', ''))) < 10)
print(f'  ✅ 有完整示例: {has_example}')
print(f'  ⚠️ 示例不足: {no_example}')
"

# 检查量化术语污染（不应该出现的词汇）
echo ""
echo "🔍 量化术语检查（user_description）:"
FORBIDDEN_WORDS=("夏普" "阿尔法" "贝塔" "回撤率" "IC/IR" "因子暴露" "alpha" "beta" "sharpe")
for word in "${FORBIDDEN_WORDS[@]}"; do
    MATCHES=$(python3 -c "
import json
d = json.load(open('$OUTPUT_FILE'))
for cid, data in d.items():
    desc = data.get('user_description', '') + data.get('how_it_works', '')
    if '$word' in desc:
        print(f'  ⚠️ {cid}: 含\"$word\"')
" 2>/dev/null)
    if [ -n "$MATCHES" ]; then
        echo "$MATCHES"
    fi
done
echo "  ✅ 量化术语检查完成"

echo ""
echo "📝 验证完成！"
echo "   建议: 人工抽查 5-10 条 conditions_input.json 中的示例条件"
echo "         确认生成质量符合预期后再全量生成"
