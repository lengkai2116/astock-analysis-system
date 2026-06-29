#!/usr/bin/env python3
"""
条件说明生成 — 独立 Web UI 服务器

提供独立端口的图形化界面，用于：
  - 查看条件清单
  - 启动/停止生成任务
  - 实时查看生成进度和日志
  - 预览和下载生成结果

启动方式：
  python3 ui_server.py              # 默认端口 8765
  python3 ui_server.py --port 8888  # 自定义端口
  python3 ui_server.py --deepseek   # 默认使用 DeepSeek（不询问）

打开浏览器访问：http://localhost:8765
"""
import argparse
import json
import os
import queue
import subprocess
import sys
import threading
import time
from datetime import datetime
from http.server import HTTPServer, BaseHTTPRequestHandler
from pathlib import Path
from typing import Dict, List, Optional, Tuple
from urllib.parse import urlparse, parse_qs

# 加载项目根目录 .env（使其中的 DEEPSEEK_API_KEY 生效）
_env_path = Path(__file__).resolve().parent.parent.parent / ".env"
if _env_path.exists():
    for _line in _env_path.read_text(encoding="utf-8").splitlines():
        _line = _line.strip()
        if _line and not _line.startswith("#") and "=" in _line:
            _k, _v = _line.split("=", 1)
            os.environ.setdefault(_k.strip(), _v.strip())

SCRIPT_DIR = Path(__file__).parent
INPUT_FILE = SCRIPT_DIR / "conditions_input.json"
OUTPUT_DIR = SCRIPT_DIR / "output"
OUTPUT_FILE = OUTPUT_DIR / "condition_descriptions.json"
CHECKPOINT_FILE = OUTPUT_DIR / "_checkpoint.json"
LOG_FILE = OUTPUT_DIR / "_generation_log.txt"
GENERATION_SCRIPT = SCRIPT_DIR / "generate_condition_descriptions.py"
LMSTUDIO_BASE_URL = os.environ.get("LMSTUDIO_BASE_URL", "http://192.168.3.1:1234")

# LLM Wiki 知识库路径（用于 DeepSeek V4 上下文增强）
_WIKI_PATH = Path("/Users/kalence/Desktop/未命名文件夹/A股研究/wiki")
WIKI_BASE_PATH = _WIKI_PATH if _WIKI_PATH.exists() else None
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)


def log_msg(msg: str):
    """写入日志（同时输出到 stdout，UI 前端通过 /api/logs 拉取）"""
    timestamp = time.strftime("%H:%M:%S")
    line = f"[{timestamp}] {msg}"
    print(line)
    try:
        with open(LOG_FILE, "a", encoding="utf-8") as f:
            f.write(line + "\n")
    except Exception:
        pass


# ── 生成任务管理器 ────────────────────────────────────────

class GenerationTask:
    """管理生成任务的启动/停止/状态追踪（内嵌 DeepSeek 调用，不经过子进程）"""

    def __init__(self):
        self.status = "idle"  # idle | running | completed | failed
        self.start_time: float | None = None
        self.provider = "lmstudio"
        self.stop_flag = threading.Event()
        self._worker: threading.Thread | None = None
        self._progress: dict = {
            "completed_ids": [],
            "results": {},
            "total": 0,
        }
        self._lock = threading.Lock()

    def start(self, provider: str = "lmstudio"):
        with self._lock:
            if self._worker and self._worker.is_alive():
                return False, "已有任务正在运行"

            # 清理旧输出
            if CHECKPOINT_FILE.exists():
                CHECKPOINT_FILE.unlink()
            if LOG_FILE.exists():
                LOG_FILE.unlink()
            if OUTPUT_FILE.exists():
                OUTPUT_FILE.unlink()

            if provider == "deepseek":
                self._progress = {"completed_ids": [], "results": {}, "total": 0}
                self.status = "running"
                self.start_time = time.time()
                self.provider = provider
                self.stop_flag.clear()

                self._worker = threading.Thread(target=self._run_deepseek, daemon=True)
                self._worker.start()
                return True, "DeepSeek 任务已启动（内嵌模式）"
            else:
                # LM Studio 保持子进程模式
                return self._start_lmstudio()

        return False, "未知 provider: {provider}"

    def _start_lmstudio(self):
        """LM Studio 模式：子进程（沿用旧逻辑）"""
        import subprocess
        env = os.environ.copy()
        env["LLM_PROVIDER"] = "lmstudio"
        env["PYTHONUNBUFFERED"] = "1"
        self.status = "running"
        self.start_time = time.time()
        self.provider = "lmstudio"
        self.stop_flag.clear()

        self._process = subprocess.Popen(
            [sys.executable, str(GENERATION_SCRIPT)],
            env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
            text=True, cwd=str(SCRIPT_DIR),
        )
        self._log_thread = threading.Thread(target=self._collect_logs, daemon=True)
        self._log_thread.start()
        return True, "LM Studio 任务已启动（子进程模式）"

    def _run_deepseek(self):
        """内嵌 DeepSeek 生成：直接 API 调用，逐条生成并保存进度"""
        try:
            log_msg("🚀 开始 DeepSeek V4 内嵌生成...")

            # 加载条件清单
            if not INPUT_FILE.exists():
                log_msg(f"❌ 未找到条件清单: {INPUT_FILE}")
                with self._lock:
                    self.status = "failed"
                return

            conditions = json.loads(INPUT_FILE.read_text(encoding="utf-8"))
            total = len(conditions)
            with self._lock:
                self._progress["total"] = total

            log_msg(f"📋 加载 {total} 条条件")

            import requests

            DEEPSEEK_API_KEY = os.environ.get("DEEPSEEK_API_KEY", "")
            if not DEEPSEEK_API_KEY:
                log_msg("❌ DEEPSEEK_API_KEY 未设置")
                with self._lock:
                    self.status = "failed"
                return

            DEEPSEEK_MODEL = os.environ.get("DEEPSEEK_MODEL", "deepseek-v4-flash")
            WIKI_BASE = Path("/Users/kalence/Desktop/未命名文件夹/A股研究/wiki")
            if not WIKI_BASE.exists():
                WIKI_BASE = None
                log_msg("⚠️ Wiki 知识库未找到")

            def make_api_call(prompt_text):
                """对 DeepSeek 发起一次 API 调用（不设 proxies，直接使用系统默认网络配置）"""
                url = "https://api.deepseek.com/v1/chat/completions"
                headers = {
                    "Content-Type": "application/json",
                    "Authorization": f"Bearer {DEEPSEEK_API_KEY}",
                }
                payload = {
                    "model": DEEPSEEK_MODEL,
                    "messages": [
                        {"role": "system", "content": "你是一个专业的A股条件说明生成器。请严格按JSON格式输出，不要包含任何markdown代码块标记，只输出纯JSON。"},
                        {"role": "user", "content": prompt_text},
                    ],
                    "temperature": 0.3,
                    "max_tokens": 2048,
                }
                for attempt in range(3):
                    if self.stop_flag.is_set():
                        return None
                    try:
                        resp = requests.post(url, json=payload, headers=headers, timeout=30)
                        if resp.status_code == 200:
                            return resp.json()["choices"][0]["message"]["content"]
                        log_msg(f"⚠️ DeepSeek HTTP {resp.status_code} (尝试 {attempt+1}): {resp.text[:200]}")
                        time.sleep(2)
                    except Exception as e:
                        log_msg(f"⚠️ DeepSeek API 失败 (尝试 {attempt+1}): {str(e)[:80]}")
                        time.sleep(2)
                return None

            def load_wiki_text(wiki_sources):
                """加载 wiki 知识库文件内容"""
                if not WIKI_BASE or not wiki_sources:
                    return "（无可用知识库文件）"
                parts = []
                for source in wiki_sources:
                    fpath = WIKI_BASE / source
                    if fpath.exists():
                        text = fpath.read_text(encoding="utf-8")
                        parts.append(f"--- {source} ---\n{text[:2000]}")
                        log_msg(f"📖 加载知识库: {source} ({len(text)}字→取2000字)")
                    else:
                        found = list(WIKI_BASE.rglob(f"*{Path(source).stem}*"))
                        if found:
                            alt = found[0].relative_to(WIKI_BASE)
                            parts.append(f"--- {alt} (替代) ---\n{found[0].read_text(encoding='utf-8')[:1500]}")
                return "\n\n".join(parts) if parts else "（知识库文件未找到）"

            def build_prompt(cond, wiki_content):
                return f"""根据以下条件，生成7个说明字段（纯JSON，不要markdown代码块）：

条件：{cond['name']}
分类：{' > '.join(cond.get('category_path', [cond.get('category', '未分类')]))}
难度：{cond.get('difficulty_level', '入门')}
参数：{json.dumps(cond.get('default_params', {}), ensure_ascii=False)}

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

            success = 0
            fail = 0

            for idx, cond in enumerate(conditions, 1):
                if self.stop_flag.is_set():
                    log_msg("⏹ 任务被用户中止")
                    break

                cid = cond["condition_id"]
                log_msg(f"[{idx}/{total}] {cond['name']} ({cid}) ...")

                prompt = build_prompt(cond, load_wiki_text(cond.get("wiki_sources", [])))
                raw = make_api_call(prompt)

                if raw:
                    # 复制 generate_condition_descriptions.py 的解析逻辑
                    parsed = self._parse_deepseek_output(raw, cid)
                else:
                    parsed = self._fallback(cid)

                with self._lock:
                    self._progress["results"][cid] = parsed
                    self._progress["completed_ids"].append(cid)

                valid = bool(raw and parsed.get("user_description")
                            and parsed["user_description"] != f"等待生成说明 - {cid}")
                if valid:
                    success += 1
                    log_msg(f"  ✅")
                else:
                    fail += 1
                    log_msg(f"  ⚠️")

                # 每 5 条自动保存检查点
                if idx % 5 == 0 or idx == total:
                    self._save_checkpoint()

            # 最终输出
            self._save_output()
            log_msg(f"📊 汇总: {total} 总条件 | {success} 成功 / {fail} 失败")

            with self._lock:
                self.status = "completed" if not self.stop_flag.is_set() else "failed"

        except Exception as e:
            log_msg(f"❌ 生成过程异常: {e}")
            import traceback
            for line in traceback.format_exc().split("\n")[-5:]:
                log_msg(f"  {line}")
            with self._lock:
                self.status = "failed"
            self._save_output()

    def _parse_deepseek_output(self, content, condition_id):
        """解析 DeepSeek 输出 JSON（三段式容错）"""
        content = content.strip()
        if content.startswith("```"):
            content = content.split("\n", 1)[-1]
        if content.endswith("```"):
            content = content.rsplit("\n", 1)[0]
        content = content.strip()

        start = content.find("{")
        end = content.rfind("}")
        if start < 0 or end <= start:
            return self._fallback(condition_id)
        json_str = content[start:end+1]

        # ① 标准 JSON
        try:
            parsed = json.loads(json_str)
            if "user_description" in parsed:
                return parsed
        except json.JSONDecodeError:
            pass

        # ② 修复换行后重试
        fixed = self._fix_json_string(json_str)
        try:
            parsed = json.loads(fixed)
            if "user_description" in parsed:
                log_msg(f"🔧 {condition_id}: JSON 修复成功")
                return parsed
        except json.JSONDecodeError:
            pass

        # ③ 正则提取
        import re
        result = {}
        for field in ["user_description", "how_it_works", "when_to_use", "when_not_to_use", "example"]:
            m = re.search(rf'"{field}"\s*:\s*"([^"]*)"', json_str)
            if m:
                result[field] = m.group(1)
        if result.get("user_description"):
            result["parameter_descriptions"] = ""
            result["related_conditions"] = []
            return result

        return self._fallback(condition_id)

    def _fix_json_string(self, s):
        """修复 JSON 字符串中的未转义换行"""
        result = []
        in_string = False
        escape = False
        for ch in s:
            if escape:
                result.append(ch); escape = False; continue
            if ch == '\\':
                result.append(ch); escape = True; continue
            if ch == '"' and not escape:
                in_string = not in_string; result.append(ch); continue
            if in_string and ch == '\n':
                result.append('\\n'); continue
            result.append(ch)
        return ''.join(result)

    def _fallback(self, condition_id):
        return {
            "user_description": f"等待生成说明 - {condition_id}",
            "how_it_works": "请重新生成此条件的说明",
            "parameter_descriptions": "",
            "when_to_use": "",
            "when_not_to_use": "",
            "example": "",
            "related_conditions": [],
        }

    def _save_checkpoint(self):
        """保存检查点"""
        with self._lock:
            cp = {
                "completed": self._progress["completed_ids"],
                "results": self._progress["results"],
            }
        try:
            CHECKPOINT_FILE.write_text(json.dumps(cp, ensure_ascii=False, indent=2), encoding="utf-8")
        except Exception as e:
            log_msg(f"⚠️ 检查点保存失败: {e}")

    def _save_output(self):
        """保存最终输出"""
        with self._lock:
            results = self._progress["results"].copy()
        try:
            OUTPUT_FILE.write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")
            log_msg(f"📝 输出已保存到 {OUTPUT_FILE.name}")
        except Exception as e:
            log_msg(f"⚠️ 输出保存失败: {e}")

    def _collect_logs(self):
        """收集子进程输出（仅 LM Studio 模式）"""
        try:
            with open(LOG_FILE, "a", encoding="utf-8") as log_f:
                for line in iter(self._process.stdout.readline, ""):
                    log_f.write(line)
                    log_f.flush()
                    if self.stop_flag.is_set():
                        break
        except Exception:
            pass
        finally:
            with self._lock:
                if self._process and self._process.poll() is not None:
                    self.status = "completed" if self._process.returncode == 0 else "failed"

    def stop(self):
        with self._lock:
            self.stop_flag.set()
            if hasattr(self, '_process') and self._process and self._process.poll() is None:
                self._process.terminate()
            self.status = "failed"
        return True, "任务已终止"

    def get_progress(self) -> dict:
        """获取当前进度"""
        with self._lock:
            done = (self._progress["completed_ids"] or [])
            total = self._progress.get("total", 0)
            return {
                "status": self.status,
                "provider": self.provider,
                "elapsed": round(time.time() - self.start_time, 1) if self.start_time else 0,
                "completed_count": len(done),
                "completed_ids": done,
                "total_count": total,
                "result_count": len(self._progress.get("results", {})),
            }

    def get_logs(self, tail: int = 50) -> list:
        """获取最近的日志行"""
        if not LOG_FILE.exists():
            return []
        try:
            lines = LOG_FILE.read_text(encoding="utf-8").strip().split("\n")
            return lines[-tail:]
        except Exception:
            return []

    def get_results(self) -> Optional[dict]:
        """获取生成结果"""
        if not OUTPUT_FILE.exists():
            return None
        try:
            return json.loads(OUTPUT_FILE.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, Exception):
            return None


task_manager = GenerationTask()
def check_lmstudio() -> dict:
    """检查 LM Studio 是否在运行"""
    import urllib.request
    try:
        req = urllib.request.Request(f"{LMSTUDIO_BASE_URL}/v1/models", method="GET")
        with urllib.request.urlopen(req, timeout=5) as resp:
            data = json.loads(resp.read().decode())
            models = [m["id"] for m in data.get("data", [])]
            return {"online": True, "models": models, "url": LMSTUDIO_BASE_URL}
    except Exception as e:
        return {"online": False, "models": [], "url": LMSTUDIO_BASE_URL, "error": str(e)}


# ── HTTP 服务器 ──────────────────────────────────────────

PORT = 8765


class UIHandler(BaseHTTPRequestHandler):

    def log_message(self, format, *args):
        """抑制默认的日志输出（更友好）"""
        if args and "favicon" not in str(args[0]):
            print(f"[UI] {self.client_address[0]} - {format % args}")

    def _send_json(self, data, status=200):
        body = json.dumps(data, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _send_html(self, html: str, status=200):
        body = html.encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _send_file(self, path: Path):
        if not path.exists():
            self._send_json({"error": "文件不存在"}, 404)
            return
        body = path.read_bytes()
        ext = path.suffix.lower()
        mime = {
            ".json": "application/json; charset=utf-8",
            ".html": "text/html; charset=utf-8",
            ".css": "text/css; charset=utf-8",
            ".js": "application/javascript; charset=utf-8",
        }.get(ext, "application/octet-stream")

        self.send_response(200)
        self.send_header("Content-Type", mime)
        self.send_header("Access-Control-Allow-Origin", "*")
        if ext == ".json":
            self.send_header("Content-Disposition", f'attachment; filename="{path.name}"')
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        parsed = urlparse(self.path)
        path = parsed.path.rstrip("/")
        params = parse_qs(parsed.query)

        # ── API 路由 ──
        if path == "/api/status":
            lmstudio = check_lmstudio()
            progress = task_manager.get_progress()
            self._send_json({
                "server": {"version": "1.0", "port": PORT},
                "lmstudio": lmstudio,
                "task": progress,
                "input_exists": INPUT_FILE.exists(),
                "output_exists": OUTPUT_FILE.exists(),
            })

        elif path == "/api/progress":
            self._send_json(task_manager.get_progress())

        elif path == "/api/logs":
            tail = int(params.get("tail", [50])[0])
            self._send_json({"lines": task_manager.get_logs(tail)})

        elif path == "/api/conditions":
            if INPUT_FILE.exists():
                conditions = json.loads(INPUT_FILE.read_text(encoding="utf-8"))
                self._send_json({"conditions": conditions, "total": len(conditions)})
            else:
                self._send_json({"conditions": [], "total": 0, "error": "conditions_input.json 未找到"})

        elif path == "/api/wiki-status":
            """返回 LLM Wiki 知识库关联状态"""
            conditions_file = INPUT_FILE
            total_conditions = 0
            conditions_with_wiki = 0
            conditions_without_wiki = 0
            if conditions_file.exists() and WIKI_BASE_PATH:
                conditions = json.loads(conditions_file.read_text(encoding="utf-8"))
                total_conditions = len(conditions)
                for c in conditions:
                    if c.get("wiki_sources"):
                        conditions_with_wiki += 1
                    else:
                        conditions_without_wiki += 1
            self._send_json({
                "wiki_online": WIKI_BASE_PATH is not None,
                "wiki_path": str(WIKI_BASE_PATH) if WIKI_BASE_PATH else None,
                "total_conditions": total_conditions,
                "conditions_with_wiki": conditions_with_wiki,
                "conditions_without_wiki": conditions_without_wiki,
            })

        elif path == "/api/results":
            results = task_manager.get_results()
            if results:
                conditions = json.loads(INPUT_FILE.read_text(encoding="utf-8")) if INPUT_FILE.exists() else []
                cid_map = {c["condition_id"]: c["name"] for c in conditions}
                items = []
                for cid, desc in results.items():
                    items.append({
                        "condition_id": cid,
                        "name": cid_map.get(cid, cid),
                        "description": desc.get("user_description", ""),
                        "how_it_works": desc.get("how_it_works", ""),
                        "has_example": bool(desc.get("example", "")),
                    })
                self._send_json({
                    "total": len(items),
                    "items": items,
                    "raw": results,
                })
            else:
                self._send_json({"total": 0, "items": [], "raw": {}})

        elif path == "/api/results/download":
            self._send_file(OUTPUT_FILE)

        elif path == "/api/check-lmstudio":
            self._send_json(check_lmstudio())

        # ── 主页面 ──
        elif path == "/" or path == "":
            self._send_html(INDEX_HTML)

        else:
            self._send_json({"error": "未找到路由"}, 404)

    def do_POST(self):
        parsed = urlparse(self.path)
        path = parsed.path.rstrip("/")

        content_length = int(self.headers.get("Content-Length", 0))
        body = self.rfile.read(content_length) if content_length else b"{}"
        try:
            data = json.loads(body.decode("utf-8"))
        except json.JSONDecodeError:
            data = {}

        if path == "/api/start":
            provider = data.get("provider", "lmstudio")
            success, message = task_manager.start(provider)
            self._send_json({"success": success, "message": message},
                            status=200 if success else 409)

        elif path == "/api/stop":
            success, message = task_manager.stop()
            self._send_json({"success": success, "message": message})

        elif path == "/api/check-lmstudio":
            self._send_json(check_lmstudio())

        else:
            self._send_json({"error": "未找到路由"}, 404)


# ── HTML 页面 ────────────────────────────────────────────

INDEX_HTML = r"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>条件说明生成器</title>
<style>
  :root {
    --bg: #0f0f14;
    --surface: #1a1a24;
    --border: #2a2a3a;
    --text: #e0e0e8;
    --text-dim: #8888a0;
    --green: #22c55e;
    --red: #ef4444;
    --yellow: #eab308;
    --blue: #3b82f6;
    --accent: #6366f1;
  }
  * { margin: 0; padding: 0; box-sizing: border-box; }
  body {
    font-family: -apple-system, "PingFang SC", "Microsoft YaHei", sans-serif;
    background: var(--bg);
    color: var(--text);
    min-height: 100vh;
  }
  .container { max-width: 960px; margin: 0 auto; padding: 20px; }

  /* 头部 */
  .header {
    display: flex; align-items: center; justify-content: space-between;
    padding: 16px 24px; background: var(--surface);
    border-bottom: 1px solid var(--border); margin-bottom: 20px;
  }
  .header h1 { font-size: 18px; font-weight: 600; }
  .header .subtitle { font-size: 12px; color: var(--text-dim); }

  /* 卡片 */
  .card {
    background: var(--surface); border: 1px solid var(--border);
    border-radius: 8px; padding: 20px; margin-bottom: 16px;
  }
  .card-title {
    font-size: 14px; font-weight: 600; margin-bottom: 12px;
    display: flex; align-items: center; gap: 8px;
  }

  /* 状态栏 */
  .status-bar {
    display: flex; gap: 12px; flex-wrap: wrap; margin-bottom: 16px;
  }
  .status-item {
    flex: 1; min-width: 120px; background: var(--surface);
    border: 1px solid var(--border); border-radius: 8px;
    padding: 12px 16px; text-align: center;
  }
  .status-item .label { font-size: 11px; color: var(--text-dim); }
  .status-item .value { font-size: 24px; font-weight: 700; margin-top: 4px; }

  /* 按钮 */
  .btn {
    display: inline-flex; align-items: center; gap: 6px;
    padding: 8px 18px; border: none; border-radius: 6px;
    font-size: 14px; cursor: pointer; transition: .15s;
  }
  .btn-primary { background: var(--accent); color: white; }
  .btn-primary:hover { opacity: .85; }
  .btn-primary:disabled { opacity: .4; cursor: not-allowed; }
  .btn-danger { background: var(--red); color: white; }
  .btn-danger:hover { opacity: .85; }
  .btn-danger:disabled { opacity: .4; cursor: not-allowed; }
  .btn-outline {
    background: transparent; border: 1px solid var(--border); color: var(--text);
  }
  .btn-outline:hover { border-color: var(--accent); }

  /* 进度条 */
  .progress-bar {
    width: 100%; height: 6px; background: var(--border);
    border-radius: 3px; overflow: hidden; margin: 8px 0;
  }
  .progress-fill {
    height: 100%; background: var(--accent); transition: width .5s ease;
    border-radius: 3px;
  }

  /* 日志 */
  .log-area {
    background: #0a0a10; border: 1px solid var(--border);
    border-radius: 6px; padding: 12px; font-family: "SF Mono", Menlo, monospace;
    font-size: 12px; line-height: 1.6; max-height: 300px; overflow-y: auto;
    white-space: pre-wrap; word-break: break-all;
  }
  .log-area .time { color: #666; }
  .log-area .ok { color: var(--green); }
  .log-area .warn { color: var(--yellow); }
  .log-area .err { color: var(--red); }
  .log-area .info { color: var(--blue); }

  /* 条件列表 */
  .condition-item {
    display: flex; align-items: center; justify-content: space-between;
    padding: 8px 12px; border-bottom: 1px solid var(--border);
    font-size: 13px; gap: 8px;
  }
  .condition-item:last-child { border-bottom: none; }
  .condition-item .name { flex: 1; }
  .condition-item .badge {
    font-size: 11px; padding: 2px 8px; border-radius: 4px; white-space: nowrap;
  }
  .badge-ready { background: rgba(34,197,94,.15); color: var(--green); }
  .badge-done { background: rgba(59,130,246,.15); color: var(--blue); }
  .badge-pending { background: rgba(234,179,8,.15); color: var(--yellow); }
  .badge-fail { background: rgba(239,68,68,.15); color: var(--red); }

  /* 结果卡片 */
  .result-item {
    border: 1px solid var(--border); border-radius: 6px;
    padding: 12px; margin-bottom: 8px; font-size: 13px;
  }
  .result-item .r-name { font-weight: 600; margin-bottom: 4px; }
  .result-item .r-desc { color: var(--text-dim); font-size: 12px; }

  /* Tab */
  .tabs { display: flex; gap: 2px; margin-bottom: 16px; }
  .tab {
    padding: 8px 16px; background: var(--surface); border: 1px solid var(--border);
    border-bottom: none; border-radius: 6px 6px 0 0; cursor: pointer;
    font-size: 13px; color: var(--text-dim); transition: .15s;
  }
  .tab.active { color: var(--text); border-color: var(--accent); background: var(--surface); }
  .tab:hover { color: var(--text); }
  .tab-panel { display: none; }
  .tab-panel.active { display: block; }

  /* 工具提示 */
  .tooltip { font-size: 11px; color: var(--text-dim); margin-top: 4px; }

  .flex { display: flex; gap: 8px; align-items: center; }
  .flex-wrap { flex-wrap: wrap; }
  .mt-12 { margin-top: 12px; }
  .mb-8 { margin-bottom: 8px; }
  .gap-8 { gap: 8px; }
  .hidden { display: none; }
  .text-green { color: var(--green); }
  .text-red { color: var(--red); }
  .text-yellow { color: var(--yellow); }

  @media (max-width: 640px) {
    .status-bar { flex-direction: column; }
    .header { flex-direction: column; align-items: flex-start; gap: 8px; }
  }
</style>
</head>
<body>

<div class="header">
  <div>
    <h1>📡 条件说明生成器</h1>
    <div class="subtitle">DeepSeek V4 · LLM Wiki · 内嵌模式</div>
  </div>
  <div class="flex gap-8" style="flex-wrap:wrap;">
    <span id="wikiStatus" style="font-size:12px; padding:4px 10px; border-radius:4px; background:var(--surface); border:1px solid var(--border);">📚 Wiki: 未关联</span>
    <button class="btn btn-outline" onclick="checkLMStudio()">🔍 检测 LM Studio</button>
    <span id="lmStatus" style="font-size:13px; color:var(--text-dim);">未检测</span>
  </div>
</div>

<div class="container">

  <!-- 状态卡片 -->
  <div class="status-bar">
    <div class="status-item">
      <div class="label">任务状态</div>
      <div class="value" id="taskStatus">空闲</div>
    </div>
    <div class="status-item">
      <div class="label">进度</div>
      <div class="value" id="progressText">0/0</div>
    </div>
    <div class="status-item">
      <div class="label">运行时间</div>
      <div class="value" id="elapsed">--</div>
    </div>
    <div class="status-item">
      <div class="label">引擎</div>
      <div class="value" id="provider" style="font-size:16px;">--</div>
    </div>
  </div>

  <!-- 操作按钮 -->
  <div class="card">
    <div class="card-title">🎮 控制面板</div>
    <div class="flex flex-wrap gap-8">
      <button class="btn btn-primary" id="btnStart" onclick="startGeneration()">▶ 开始生成</button>
      <button class="btn btn-danger" id="btnStop" onclick="stopGeneration()" disabled>⏹ 停止</button>
      <select id="providerSelect" style="background:var(--surface);color:var(--text);border:1px solid var(--border);border-radius:6px;padding:8px 12px;font-size:14px;">
        <option value="lmstudio">🧠 LM Studio (本地)</option>
        <option value="deepseek">☁️ DeepSeek V4 (云端)</option>
      </select>
    </div>
    <div class="progress-bar mt-12" id="progressBarContainer">
      <div class="progress-fill" id="progressFill" style="width:0%"></div>
    </div>
    <div class="tooltip" id="progressDetail">等待启动...</div>
  </div>

  <!-- Tabs -->
  <div class="tabs">
    <div class="tab active" onclick="switchTab('log', this)">📋 日志</div>
    <div class="tab" onclick="switchTab('conditions', this)">📦 条件清单</div>
    <div class="tab" onclick="switchTab('results', this)">✅ 结果</div>
  </div>

  <!-- Tab: 日志 -->
  <div class="tab-panel active" id="panel-log">
    <div class="card">
      <div class="card-title">
        📋 运行日志
        <span style="font-size:11px;color:var(--text-dim);margin-left:auto;" id="logCount">0 条</span>
      </div>
      <div class="log-area" id="logArea">等待启动...</div>
    </div>
  </div>

  <!-- Tab: 条件清单 -->
  <div class="tab-panel" id="panel-conditions">
    <div class="card">
      <div class="card-title">
        📦 条件清单
        <span style="font-size:11px;color:var(--text-dim);margin-left:auto;" id="conditionCount">加载中...</span>
      </div>
      <div id="conditionList"></div>
    </div>
  </div>

  <!-- Tab: 结果 -->
  <div class="tab-panel" id="panel-results">
    <div class="card">
      <div class="card-title">
        ✅ 生成结果
        <span style="font-size:11px;color:var(--text-dim);margin-left:auto;" id="resultCount">0 条</span>
      </div>
      <div class="flex mb-8">
        <button class="btn btn-outline" onclick="refreshResults()">🔄 刷新</button>
        <button class="btn btn-outline" onclick="downloadResults()">📥 下载 JSON</button>
      </div>
      <div id="resultList"></div>
    </div>
  </div>

</div>

<script>
// ── 状态管理 ──
let pollInterval = null;
let logPollInterval = null;

// ── Tab 切换 ──
function switchTab(name, el) {
  document.querySelectorAll('.tab').forEach(t => t.classList.remove('active'));
  document.querySelectorAll('.tab-panel').forEach(p => p.classList.remove('active'));
  el.classList.add('active');
  document.getElementById('panel-' + name).classList.add('active');
  if (name === 'conditions') loadConditions();
  if (name === 'results') refreshResults();
}

// ── LM Studio 检测 ──
async function checkLMStudio() {
  const el = document.getElementById('lmStatus');
  el.textContent = '检测中...';
  try {
    const resp = await fetch('/api/check-lmstudio');
    const data = await resp.json();
    if (data.online) {
      el.innerHTML = '<span class="text-green">✅ 已连接</span>';
    } else {
      el.innerHTML = '<span class="text-red">❌ 未连接</span>';
    }
  } catch {
    el.innerHTML = '<span class="text-red">❌ 请求失败</span>';
  }
}

// ── 开始生成 ──
async function startGeneration() {
  const provider = document.getElementById('providerSelect').value;
  const btn = document.getElementById('btnStart');
  btn.disabled = true;
  btn.textContent = '⏳ 启动中...';

  try {
    const resp = await fetch('/api/start', {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({provider}),
    });
    const data = await resp.json();
    if (data.success) {
      startPolling();
      document.getElementById('btnStop').disabled = false;
    } else {
      alert(data.message);
      btn.disabled = false;
      btn.textContent = '▶ 开始生成';
    }
  } catch (e) {
    alert('启动失败: ' + e.message);
    btn.disabled = false;
    btn.textContent = '▶ 开始生成';
  }
}

// ── 停止生成 ──
async function stopGeneration() {
  if (!confirm('确定要停止当前任务？')) return;
  try {
    const resp = await fetch('/api/stop', {method: 'POST'});
    const data = await resp.json();
    if (data.success) {
      stopPolling();
    }
  } catch (e) {
    console.error('停止失败:', e);
  }
}

// ── 轮询 ──
function startPolling() {
  if (pollInterval) clearInterval(pollInterval);
  loadConditions();
  pollInterval = setInterval(updateProgress, 1000);
  logPollInterval = setInterval(updateLogs, 2000);
  updateProgress();
  updateLogs();
}

function stopPolling() {
  if (pollInterval) { clearInterval(pollInterval); pollInterval = null; }
  if (logPollInterval) { clearInterval(logPollInterval); logPollInterval = null; }
}

async function updateProgress() {
  try {
    const resp = await fetch('/api/progress');
    const data = await resp.json();

    const total = data.total_count || 0;
    const done = data.completed_count || 0;
    const pct = total > 0 ? Math.round(done / total * 100) : 0;

    document.getElementById('taskStatus').textContent =
      data.status === 'idle' ? '空闲' :
      data.status === 'running' ? '⏳ 运行中' :
      data.status === 'completed' ? '✅ 已完成' :
      data.status === 'failed' ? '❌ 已终止' : data.status;
    document.getElementById('progressText').textContent = `${done}/${total}`;
    document.getElementById('elapsed').textContent =
      data.elapsed ? formatTime(data.elapsed) : '--';
    document.getElementById('provider').textContent =
      data.provider === 'lmstudio' ? '🧠 LM Studio' : '☁️ DeepSeek';
    document.getElementById('progressFill').style.width = pct + '%';
    document.getElementById('progressDetail').textContent =
      data.status === 'running' ? `已生成 ${done}/${total} 条 (${pct}%)` :
      data.status === 'completed' ? `✅ 已完成 ${done} 条` :
      data.status === 'failed' ? `❌ 已终止，已完成 ${done} 条` :
      '等待启动...';

    // 更新按钮状态
    const btnStart = document.getElementById('btnStart');
    const btnStop = document.getElementById('btnStop');
    if (data.status === 'running') {
      btnStart.disabled = true; btnStart.textContent = '▶ 开始生成';
      btnStop.disabled = false;
    } else if (data.status === 'completed' || data.status === 'failed') {
      btnStart.disabled = false; btnStart.textContent = '▶ 开始生成';
      btnStop.disabled = true;
      if (data.status === 'completed') {
        // 自动加载结果
        setTimeout(loadResults, 500);
      }
    } else {
      btnStart.disabled = false; btnStart.textContent = '▶ 开始生成';
      btnStop.disabled = true;
    }

    // 检查是否完成，停止轮询
    if (data.status === 'completed' || data.status === 'failed') {
      stopPolling();
    }
  } catch (e) {
    console.error('进度更新失败:', e);
  }
}

async function updateLogs() {
  try {
    const resp = await fetch('/api/logs?tail=100');
    const data = await resp.json();
    if (data.lines && data.lines.length > 0) {
      const logArea = document.getElementById('logArea');
      const html = data.lines.map(line => escapeHtml(line)).join('\n');
      logArea.innerHTML = html;
      logArea.scrollTop = logArea.scrollHeight;
      document.getElementById('logCount').textContent = data.lines.length + ' 条';
    }
  } catch (e) { /* ignore */ }
}

async function loadConditions() {
  try {
    const resp = await fetch('/api/conditions');
    const data = await resp.json();
    const list = document.getElementById('conditionList');
    document.getElementById('conditionCount').textContent = data.total + ' 条';

    if (!data.conditions || data.conditions.length === 0) {
      list.innerHTML = '<div style="color:var(--text-dim);padding:12px;text-align:center;">暂无条件数据</div>';
      return;
    }

    // 获取已完成的ID
    let doneIds = [];
    try {
      const p = await fetch('/api/progress');
      const pd = await p.json();
      doneIds = pd.completed_ids || [];
    } catch {}

    list.innerHTML = data.conditions.map(c => {
      const isDone = doneIds.includes(c.condition_id);
      const badge = isDone ? 'badge-done' : 'badge-pending';
      const label = isDone ? '✅ 已生成' : '⏳ 待生成';
      return `<div class="condition-item" style="flex-wrap:wrap;">
        <span class="name">${escapeHtml(c.name)}</span>
        <span class="badge ${c.difficulty_level === '入门' ? 'badge-ready' : c.difficulty_level === '进阶' ? 'badge-pending' : 'badge-fail'}" style="margin-right:8px;">${c.difficulty_level || '--'}</span>
        <span class="badge ${badge}">${label}</span>
      </div>`;
    }).join('');
  } catch (e) {
    document.getElementById('conditionList').innerHTML =
      '<div style="color:var(--red);padding:12px;">加载失败: ' + e.message + '</div>';
  }
}

async function loadResults() {
  await refreshResults();
}

async function refreshResults() {
  try {
    const resp = await fetch('/api/results');
    const data = await resp.json();
    const list = document.getElementById('resultList');
    document.getElementById('resultCount').textContent = data.total + ' 条';

    if (!data.items || data.items.length === 0) {
      list.innerHTML = '<div style="color:var(--text-dim);padding:12px;text-align:center;">暂无结果，请先生成</div>';
      return;
    }

    list.innerHTML = data.items.map(item => {
      const desc = item.description || '(无描述)';
      return `<div class="result-item">
        <div class="r-name">${escapeHtml(item.name)} <span style="font-weight:400;color:var(--text-dim);font-size:11px;">${item.condition_id}</span></div>
        <div class="r-desc">${escapeHtml(desc)}</div>
        <div style="margin-top:4px;font-size:11px;">${item.has_example ? '📌 含示例' : '⚠️ 无示例'}</div>
      </div>`;
    }).join('');
  } catch (e) {
    document.getElementById('resultList').innerHTML =
      '<div style="color:var(--red);padding:12px;">加载失败: ' + e.message + '</div>';
  }
}

function downloadResults() {
  window.open('/api/results/download', '_blank');
}

// ── 工具 ──
function formatTime(seconds) {
  const m = Math.floor(seconds / 60);
  const s = Math.floor(seconds % 60);
  return m > 0 ? `${m}分${s}秒` : `${s}秒`;
}

function escapeHtml(str) {
  const div = document.createElement('div');
  div.textContent = str || '';
  return div.innerHTML;
}

// ── Wiki 状态检查 ──
async function checkWikiStatus() {
  try {
    const resp = await fetch('/api/wiki-status');
    const data = await resp.json();
    if (data.wiki_online) {
      const pct = data.total_conditions > 0
        ? Math.round(data.conditions_with_wiki / data.total_conditions * 100)
        : 0;
      document.getElementById('wikiStatus').innerHTML =
        `<span class="text-green">📚 Wiki: 已关联 (${data.conditions_with_wiki}/${data.total_conditions} 条, ${pct}%)</span>`;
    } else {
      document.getElementById('wikiStatus').innerHTML = '📚 Wiki: 未关联';
    }
  } catch {
    document.getElementById('wikiStatus').innerHTML = '📚 Wiki: 检查失败';
  }
}

// ── 初始化 ──
checkLMStudio();
checkWikiStatus();
updateProgress();

// 检查是否有正在运行的任务
setInterval(() => {
  fetch('/api/progress').then(r => r.json()).then(d => {
    if (d.status === 'running') startPolling();
  }).catch(() => {});
}, 3000);
</script>
</body>
</html>
"""


# ── 启动 ──

def parse_args():
    parser = argparse.ArgumentParser(description="条件说明生成器 — Web UI")
    parser.add_argument("--port", type=int, default=PORT, help=f"端口号（默认 {PORT}）")
    parser.add_argument("--host", type=str, default="127.0.0.1", help="监听地址（默认 127.0.0.1）")
    parser.add_argument("--browser", action="store_true", help="启动后自动打开浏览器")
    parser.add_argument("--open", action="store_true", help="启动后自动打开浏览器")
    parser.add_argument("--deepseek", action="store_true", help="默认使用 DeepSeek（不询问）")
    return parser.parse_args()


def open_browser(url):
    import webbrowser
    time.sleep(1)
    webbrowser.open(url)


def main():
    args = parse_args()
    host, port = args.host, args.port

    # 如果指定了 --deepseek，设置环境变量
    if args.deepseek:
        os.environ.setdefault("LLM_PROVIDER", "deepseek")

    server = HTTPServer((host, port), UIHandler)
    url = f"http://{host}:{port}"

    print("=" * 50)
    print("  📡 条件说明生成器 — Web UI")
    print("=" * 50)
    print()
    print(f"  地址:    {url}")
    print(f"  端口:    {port}")
    print(f"  主机:    {host}")
    print()
    print("  功能:")
    print("    - 查看条件清单")
    print("    - 启动/停止生成任务")
    print("    - 实时查看进度和日志")
    print("    - 预览和下载生成结果")
    print()
    print("  使用方法:")
    print(f"    1. 打开浏览器访问 {url}")
    print("    2. 选择 LLM 引擎（LM Studio / DeepSeek）")
    print("    3. 点击「开始生成」")
    print("    4. 在「日志」Tab 查看实时进度")
    print("    5. 生成完成后在「结果」Tab 查看和下载")
    print()
    print("  Ctrl+C 停止服务器")
    print("=" * 50)

    # 自动打开浏览器
    if args.open or args.browser:
        threading.Thread(target=open_browser, args=(url,), daemon=True).start()

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n👋 服务器已停止")
        server.server_close()


if __name__ == "__main__":
    main()
