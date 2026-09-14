# -*- coding: utf-8 -*-
"""临时审计脚本（第一步产物）：dim2 内联 4 区块 vs framework 对应文件，符号级 + 行级 diff。

用法：python _audit_dim2_chanlun_diff.py
输出：stdout 摘要 + 详情写 /tmp/chanlun_audit/<区块>.txt
"""
import difflib
import os
import re
import sys
from pathlib import Path

ROOT = Path("/Users/kalence/Desktop/01-A股股票分析系统/backend")
DIM2 = ROOT / "app/opportunity_atlas/dimensions/dim2_structure_engine.py"
FRAMEWORK = ROOT / "app/engine/framework"
OUT = Path("/tmp/chanlun_audit")

SYMBOL_RE = re.compile(r"^(class|def) (\w+)")

# 区块标记 -> (framework 文件名, 是否存在于 framework)
BLOCKS = [
    ("chanlun_config.py", "chanlun_config.py", True),
    ("chanlun_level_validator.py", "chanlun_level_validator.py", False),  # 已删除
    ("trend_structure_detector.py", "trend_structure_detector.py", True),
    ("chanlun_strategy.py", "chanlun_strategy.py", True),
]


def extract_block(lines, marker):
    """提取 dim2 中 '# === <marker> ===' 到下一个 '# === ' 或 'class Dim2StructureEngine' 之间的行。"""
    start = None
    for i, line in enumerate(lines):
        if line.startswith(f"# === {marker} ==="):
            start = i + 1
            break
    if start is None:
        return []
    end = len(lines)
    for i in range(start, len(lines)):
        if lines[i].startswith("# === ") or lines[i].startswith("class Dim2StructureEngine"):
            end = i
            break
    return lines[start:end]


def symbols(lines):
    """返回该文本块中的顶层符号列表 [(name, kind, line_no_in_block)]"""
    out = []
    for i, line in enumerate(lines):
        m = SYMBOL_RE.match(line)
        if m:
            out.append((m.group(2), m.group(1), i + 1))
    return out


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    dim2_lines = DIM2.read_text(encoding="utf-8").splitlines()
    report = []
    for marker, fname, exists in BLOCKS:
        block = extract_block(dim2_lines, marker)
        fw_path = FRAMEWORK / fname
        print(f"\n{'='*70}\n区块: {marker}  (dim2 {len(block)} 行)")
        report.append(f"## 区块 {marker}\n")
        if not exists or not fw_path.exists():
            print(f"  framework/{fname} 不存在（{'已删除' if not exists else '缺失'}）——dim2 内联份为唯一权威")
            report.append(f"framework/{fname} 不存在（{'已删除' if not exists else '缺失'}）——dim2 内联份为唯一权威\n")
            continue
        fw_lines = fw_path.read_text(encoding="utf-8").splitlines()
        fw_no_header = [l for l in fw_lines if not l.startswith("# === ")]
        print(f"  framework/{fname} {len(fw_no_header)} 行")

        # 符号级对比
        dim2_sym = symbols(block)
        fw_sym = symbols(fw_no_header)
        dim2_names = {s[0] for s in dim2_sym}
        fw_names = {s[0] for s in fw_sym}
        only_dim2 = sorted(dim2_names - fw_names)
        only_fw = sorted(fw_names - dim2_names)
        print(f"  符号: dim2 {len(dim2_sym)} / fw {len(fw_sym)}")
        if only_dim2:
            print(f"  dim2 独有符号: {only_dim2}")
        if only_fw:
            print(f"  framework 独有符号: {only_fw}")
        report.append(f"符号: dim2 {len(dim2_sym)} / framework {len(fw_sym)}\n")
        if only_dim2:
            report.append(f"dim2 独有符号: {only_dim2}\n")
        if only_fw:
            report.append(f"framework 独有符号: {only_fw}\n")

        # 行级 diff（统一去掉行尾空白）
        a = [l.rstrip() for l in block]
        b = [l.rstrip() for l in fw_no_header]
        sm = difflib.SequenceMatcher(None, a, b)
        same = sum(s.size for s in sm.get_matching_blocks())
        total = max(len(a), len(b))
        ratio = same / total if total else 1.0
        print(f"  相似度: {ratio:.1%} (匹配 {same}/{total})")
        report.append(f"行级相似度: {ratio:.1%}（匹配 {same}/{total}）\n")

        # 详细 diff 输出
        diff = list(difflib.unified_diff(b, a, fromfile=f"framework/{fname}", tofile=f"dim2[{marker}]", lineterm=""))
        detail = OUT / f"{marker}.txt"
        detail.write_text("\n".join(diff), encoding="utf-8")
        print(f"  diff 详情 -> {detail}（{len(diff)} 行）")
        report.append(f"diff 详情: {detail}（{len(diff)} 行）\n")
    print("\n完成。")

if __name__ == "__main__":
    main()
