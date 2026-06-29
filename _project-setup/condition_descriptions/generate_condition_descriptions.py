#!/usr/bin/env python3
"""
条件说明一键生成脚本

调用本地的 LM Studio (Qwen3.5-9B) 或远程 DeepSeek V4，逐条生成条件说明。
支持断点续传、批量完成自动汇总。

使用方法：
  python3 generate_condition_descriptions.py

环境变量（可选，不设则交互式询问）：
  - LLM_PROVIDER=lmstudio|deepseek
  - LMSTUDIO_BASE_URL=http://192.168.3.1:1234
  - DEEPSEEK_API_KEY=sk-xxx
"""
import json
import os
import sys
import time
import urllib.request
import urllib.error
from pathlib import Path

# 加载项目根目录 .env（使其中的 DEEPSEEK_API_KEY 生效）
_env_path = Path(__file__).resolve().parent.parent.parent / ".env"
if _env_path.exists():
    for _line in _env_path.read_text(encoding="utf-8").splitlines():
        _line = _line.strip()
        if _line and not _line.startswith("#") and "=" in _line:
            _k, _v = _line.split("=", 1)
            os.environ.setdefault(_k.strip(), _v.strip())

# ── 路径配置 ──────────────────────────────────────────────
SCRIPT_DIR = Path(__file__).parent
INPUT_FILE = SCRIPT_DIR / "conditions_input.json"
OUTPUT_DIR = SCRIPT_DIR / "output"
OUTPUT_FILE = OUTPUT_DIR / "condition_descriptions.json"
CHECKPOINT_FILE = OUTPUT_DIR / "_checkpoint.json"
LOG_FILE = OUTPUT_DIR / "_generation_log.txt"

OUTPUT_DIR.mkdir(parents=True, exist_ok=True)


def log(msg):
    """日志输出"""
    timestamp = time.strftime("%H:%M:%S")
    line = f"[{timestamp}] {msg}"
    print(line)
    with open(LOG_FILE, "a", encoding="utf-8") as f:
        f.write(line + "\n")


# ── LLM 配置 ──────────────────────────────────────────────
LMSTUDIO_BASE_URL = os.environ.get("LMSTUDIO_BASE_URL", "http://192.168.3.1:1234")
DEEPSEEK_API_KEY = os.environ.get("DEEPSEEK_API_KEY", "")
# DeepSeek V4 — 带知识库（模型名: deepseek-v4-flash，2026年4月更新）
LLM_PROVIDER = os.environ.get("LLM_PROVIDER", "deepseek")

# DeepSeek V4 模型名（旧 deepseek-chat 已弃用，将于2026年7月24日停用）
DEEPSEEK_MODEL = os.environ.get("DEEPSEEK_MODEL", "deepseek-v4-flash")

# LLM Wiki 知识库路径（DeepSeek V4 处理长上下文无压力）
WIKI_BASE = Path("/Users/kalence/Desktop/未命名文件夹/A股研究/wiki")
if not WIKI_BASE.exists():
    WIKI_BASE = Path(__file__).resolve().parent.parent.parent / "llm_wiki"
if not WIKI_BASE.exists():
    WIKI_BASE = None
    log("⚠️ LLM Wiki 知识库未找到，将使用模型自身知识生成")


# ── LLM API 封装 ─────────────────────────────────────────

def check_lmstudio():
    """检查 LM Studio 服务状态"""
    try:
        req = urllib.request.Request(f"{LMSTUDIO_BASE_URL}/v1/models")
        with urllib.request.urlopen(req, timeout=5) as resp:
            data = json.loads(resp.read().decode())
            models = [m["id"] for m in data.get("data", [])]
            if models:
                log(f"✅ LM Studio 已连接，可用模型: {', '.join(models[:3])}...")
                return True, models
            else:
                log("⚠️ LM Studio 已连接，但未加载模型")
                return False, []
    except Exception as e:
        log(f"❌ LM Studio 连接失败: {e}")
        return False, []


def check_deepseek():
    """检查 DeepSeek API key"""
    if DEEPSEEK_API_KEY:
        log("✅ DeepSeek API key 已配置")
        return True
    else:
        log("⚠️ DeepSeek API key 未配置")
        return False


def call_lmstudio(prompt, max_retries=2):
    """调用 LM Studio API (OpenAI 兼容)"""
    url = f"{LMSTUDIO_BASE_URL}/v1/chat/completions"
    payload = json.dumps({
        "model": "qwen3.5-9b",
        "messages": [
            {"role": "system", "content": "你是一个专业的A股条件说明生成器。请严格按JSON格式输出，不要包含任何markdown代码块标记，只输出纯JSON。"},
            {"role": "user", "content": prompt}
        ],
        "temperature": 0.3,
        "max_tokens": 1024,
    }).encode("utf-8")

    for attempt in range(max_retries):
        try:
            req = urllib.request.Request(url, data=payload, headers={
                "Content-Type": "application/json"
            })
            with urllib.request.urlopen(req, timeout=180) as resp:
                body = resp.read().decode()
                result = json.loads(body)
                content = result["choices"][0]["message"]["content"]
                if not content or len(content.strip()) < 10:
                    log(f"⚠️ LM Studio 返回空内容 (尝试 {attempt+1}/{max_retries})")
                    if attempt < max_retries - 1:
                        time.sleep(5)
                    continue
                return content
        except urllib.error.HTTPError as e:
            body = e.read().decode("utf-8", errors="replace")[:200]
            log(f"⚠️ LM Studio HTTP {e.code} (尝试 {attempt+1}/{max_retries}): {body}")
            if attempt < max_retries - 1:
                time.sleep(5)
        except Exception as e:
            log(f"⚠️ LM Studio 调用失败 (尝试 {attempt+1}/{max_retries}): {e}")
            if attempt < max_retries - 1:
                time.sleep(5)
    return None


def call_deepseek(prompt, max_retries=2):
    """调用 DeepSeek V4 API"""
    import requests

    url = "https://api.deepseek.com/v1/chat/completions"
    payload = {
        "model": DEEPSEEK_MODEL,
        "messages": [
            {"role": "system", "content": "你是一个专业的A股条件说明生成器。请严格按JSON格式输出，不要包含任何markdown代码块标记，只输出纯JSON。"},
            {"role": "user", "content": prompt}
        ],
        "temperature": 0.3,
        "max_tokens": 2048,
    }
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {DEEPSEEK_API_KEY}"
    }

    for attempt in range(max_retries):
        try:
            resp = requests.post(url, json=payload, headers=headers, timeout=30)
            if resp.status_code != 200:
                log(f"⚠️ DeepSeek HTTP {resp.status_code} (尝试 {attempt+1}/{max_retries}): {resp.text[:200]}")
                if attempt < max_retries - 1:
                    time.sleep(2)
                continue
            content = resp.json()["choices"][0]["message"]["content"]
            return content
        except Exception as e:
            log(f"⚠️ DeepSeek 调用失败 (尝试 {attempt+1}/{max_retries}): {str(e)[:80]}")
            if attempt < max_retries - 1:
                time.sleep(2)
    return None


def parse_output(content, condition_id):
    """解析 LLM 输出，返回结构化描述字段"""
    if not content:
        log(f"⚠️ {condition_id}: 无输出")
        return create_fallback(condition_id)

    # 去除可能的 markdown 代码块标记
    content = content.strip()
    if content.startswith("```"):
        content = content.split("\n", 1)[-1]
    if content.endswith("```"):
        content = content.rsplit("\n", 1)[0]
    if content.endswith("```"):
        content = content[:-3]
    content = content.strip()

    # 尝试提取 JSON 对象
    start = content.find("{")
    end = content.rfind("}")
    if start < 0 or end <= start:
        log(f"❌ {condition_id}: 未找到 JSON 结构")
        return create_fallback(condition_id)

    json_str = content[start:end+1]

    # 尝试标准解析
    try:
        parsed = json.loads(json_str)
        if "user_description" in parsed:
            return parsed
    except json.JSONDecodeError:
        pass

    # 修复常见 JSON 问题后重试
    try:
        # 1. 修复字符串内未转义的换行符
        fixed = _fix_json_string(json_str)
        parsed = json.loads(fixed)
        if "user_description" in parsed:
            log(f"🔧 {condition_id}: JSON 修复成功")
            return parsed
    except json.JSONDecodeError:
        pass

    # 最后手段：逐字段正则提取
    log(f"⚠️ {condition_id}: JSON 解析失败，尝试正则提取回退...")
    parsed = _extract_fields_via_regex(json_str, condition_id)
    if parsed:
        return parsed

    log(f"❌ {condition_id}: 全部解析方式失败，使用回退说明")
    return create_fallback(condition_id)


def _fix_json_string(s):
    """修复常见 JSON 格式问题"""
    result = []
    in_string = False
    escape = False
    for ch in s:
        if escape:
            result.append(ch)
            escape = False
            continue
        if ch == '\\':
            result.append(ch)
            escape = True
            continue
        if ch == '"' and not escape:
            in_string = not in_string
            result.append(ch)
            continue
        if in_string and ch == '\n':
            result.append('\\n')
            continue
        result.append(ch)
    return ''.join(result)


def _extract_fields_via_regex(json_str, condition_id):
    """使用正则表达式逐字段提取（最终回退方案）"""
    import re
    result = {}

    # 提取 user_description
    m = re.search(r'"user_description"\s*:\s*"([^"]*)"', json_str)
    if m:
        result["user_description"] = m.group(1)
    else:
        result["user_description"] = f"等待生成说明 - {condition_id}"

    # 提取 how_it_works
    m = re.search(r'"how_it_works"\s*:\s*"([^"]*)"', json_str)
    if m:
        result["how_it_works"] = m.group(1)

    # 提取 when_to_use
    m = re.search(r'"when_to_use"\s*:\s*"([^"]*)"', json_str)
    if m:
        result["when_to_use"] = m.group(1)

    # 提取 when_not_to_use
    m = re.search(r'"when_not_to_use"\s*:\s*"([^"]*)"', json_str)
    if m:
        result["when_not_to_use"] = m.group(1)

    # 提取 example
    m = re.search(r'"example"\s*:\s*"([^"]*)"', json_str)
    if m:
        result["example"] = m.group(1)

    result["parameter_descriptions"] = ""
    result["related_conditions"] = []

    if "user_description" in result and result["user_description"] != f"等待生成说明 - {condition_id}":
        return result
    return None


def create_fallback(condition_id):
    """生成回退说明（当 LLM 调用失败时）"""
    return {
        "user_description": f"等待生成说明 - {condition_id}",
        "how_it_works": "请使用生成脚本重新生成此条件的说明",
        "parameter_descriptions": "",
        "when_to_use": "",
        "when_not_to_use": "",
        "example": "",
        "related_conditions": []
    }


def load_wiki_content(wiki_sources):
    """加载关联的 LLM Wiki 知识库文件内容

    wiki_sources 是相对 wiki/ 目录的路径列表，如：
      - "concepts/均线吻系统.md"
      - "concepts/MACD多周期结合回调买入法.md"
      - "sources/量价狙击精准捕捉股市机会.md"
    """
    if not WIKI_BASE or not wiki_sources:
        return "（无可用知识库文件）"

    contents = []
    for source in wiki_sources:
        fpath = WIKI_BASE / source
        if fpath.exists():
            try:
                text = fpath.read_text(encoding="utf-8")
                # 取前 2000 字（DeepSeek V4 长上下文无压力）
                contents.append(f"--- {source} ---\n{text[:2000]}")
                log(f"📖 加载知识库: {source} ({len(text)} 字 → 取 2000 字)")
            except Exception as e:
                log(f"⚠️ 读取知识库文件 {source} 失败: {e}")
        else:
            log(f"⚠️ 知识库文件未找到: {source}，跳过")
            # 尝试模糊搜索文件名
            found = list(WIKI_BASE.rglob(f"*{Path(source).stem}*"))
            if found:
                alt = found[0].relative_to(WIKI_BASE)
                log(f"   → 尝试替代文件: {alt}")
                try:
                    text = found[0].read_text(encoding="utf-8")
                    contents.append(f"--- {alt} ---\n{text[:1500]}")
                except Exception as e:
                    log(f"⚠️ 替代文件读取失败: {e}")

    if not contents:
        return "（知识库文件未找到）"
    return "\n\n".join(contents)


def build_prompt(condition, wiki_content):
    """组装 prompt（带 LLM Wiki 知识库，DeepSeek V4 可处理长上下文）"""
    return f"""根据以下条件，生成7个说明字段（纯JSON，不要markdown代码块）：

条件：{condition['name']}
分类：{' > '.join(condition.get('category_path', [condition.get('category', '未分类')]))}
难度：{condition.get('difficulty_level', '入门')}
参数：{json.dumps(condition.get('default_params', {}), ensure_ascii=False)}

参考知识库：
{wiki_content[:4000]}

输出如下JSON（禁止markdown代码块）：
{{
    "user_description": "一句话解释，不能出现量化术语",
    "how_it_works": "普通人能懂的逻辑（2-3句话）",
    "parameter_descriptions": {{"参数名": "自然语言说明"}},
    "when_to_use": "适用场景（2-3句话）",
    "when_not_to_use": "失效场景（2-3句话）",
    "example": "实际A股案例（含股票名和时间）",
    "related_conditions": [{{"condition_id": "...", "reason": "关联原因"}}]
}}"""


def main():
    print("=" * 60)
    print("  条件说明生成器")
    print("  支持 LM Studio (Qwen3.5-9B) / DeepSeek V4")
    print("=" * 60)

    # ── Step 1: 选择 LLM 提供者 ──
    provider = LLM_PROVIDER
    if provider == "lmstudio":
        ok, models = check_lmstudio()
        if not ok:
            log("❌ LM Studio 不可用，请先启动 LM Studio 并加载 Qwen3.5-9B 模型")
            sys.exit(1)
        print(f"\n🔵 使用 LM Studio — 本地模型: {models[0] if models else 'Qwen3.5-9B'}")
        print()
    elif provider == "deepseek":
        if not check_deepseek():
            log("❌ DeepSeek API key 未设置")
            sys.exit(1)
        print("\n🔵 使用 DeepSeek V4 — 云端生成")
        print()
    else:
        log(f"❌ 未知的 LLM_PROVIDER: {provider}，请设置为 lmstudio 或 deepseek")
        sys.exit(1)

    # ── Step 2: 加载条件清单 ──
    if not INPUT_FILE.exists():
        log(f"❌ 未找到条件清单文件: {INPUT_FILE}")
        log("   请先创建 conditions_input.json 文件")
        sys.exit(1)

    with open(INPUT_FILE, "r", encoding="utf-8") as f:
        conditions = json.load(f)

    log(f"📋 加载 {len(conditions)} 条条件")

    # ── Step 3: 检查断点续传 ──
    existing = {}
    if CHECKPOINT_FILE.exists():
        with open(CHECKPOINT_FILE, "r", encoding="utf-8") as f:
            checkpoint = json.load(f)
            done_ids = set(checkpoint.get("completed", []))
            existing.update(checkpoint.get("results", {}))
            log(f"📌 发现检查点，已完成 {len(done_ids)} 条")

            # 筛选出来完成的条件
            remaining = [c for c in conditions if c["condition_id"] not in done_ids]
            if remaining:
                log(f"  剩余 {len(remaining)} 条待生成")
            else:
                log("✅ 全部已完成！")
                # 合并输出
                final_output = existing
                with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
                    json.dump(final_output, f, ensure_ascii=False, indent=2)
                log(f"📝 已写入 {OUTPUT_FILE}")
                return
    else:
        remaining = conditions
        checkpoint = {"completed": [], "results": {}}

    # ── Step 4: 逐条生成 ──
    call_fn = call_lmstudio if provider == "lmstudio" else call_deepseek
    provider_name = "LM Studio" if provider == "lmstudio" else "DeepSeek V4"
    total = len(remaining)
    success = 0
    fail = 0

    log(f"🚀 开始使用 {provider_name} 生成说明...")
    print()

    for idx, condition in enumerate(remaining, 1):
        cid = condition["condition_id"]
        name = condition["name"]
        print(f"  [{idx}/{total}] {name} ({cid}) ... ", end="", flush=True)

        prompt = build_prompt(condition, load_wiki_content(condition.get("wiki_sources", [])))
        raw = call_fn(prompt)
        parsed = parse_output(raw, cid)

        checkpoint["results"][cid] = parsed
        checkpoint["completed"].append(cid)

        if raw and "user_description" in parsed and parsed["user_description"] != f"等待生成说明 - {cid}":
            success += 1
            print(f"✅")
        else:
            fail += 1
            print(f"⚠️")

        # 每 5 条保存一次检查点
        if idx % 5 == 0 or idx == total:
            with open(CHECKPOINT_FILE, "w", encoding="utf-8") as f:
                json.dump(checkpoint, f, ensure_ascii=False, indent=2)
            log(f"💾 自动保存检查点 ({success} 成功 / {fail} 失败)")

    # ── Step 5: 生成最终输出 ──
    final_output = checkpoint["results"]
    with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
        json.dump(final_output, f, ensure_ascii=False, indent=2)

    print()
    log(f"📊 生成汇总:")
    log(f"  - 总条件: {total}")
    log(f"  - 成功: {success}")
    log(f"  - 失败: {fail}")
    log(f"  - 输出: {OUTPUT_FILE}")

    if CHECKPOINT_FILE.exists():
        CHECKPOINT_FILE.unlink()  # 清理检查点
        log("  - 检查点已清理")


if __name__ == "__main__":
    main()
