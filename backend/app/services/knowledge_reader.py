"""
KnowledgeReader — SQLite FTS5 内嵌知识库

从 data/knowledge/concepts/ 读取 LLM Wiki 概念文件，
构建 FTS5 全文索引，提供零依赖毫秒级知识查询。

与外部 LLM Wiki 桌面 App 同源（wiki/concepts/），
作为外部服务不可用时的冷回退方案。
"""

import logging
import os
import re
import sqlite3
from pathlib import Path
from typing import Dict, List, Optional

import yaml

logger = logging.getLogger(__name__)


def _cjk_spaced(text: str) -> str:
    """在 CJK 字符间插入空格，使 FTS5 unicode61 能逐字索引中文。"""
    return re.sub(r'([\u4e00-\u9fff])', r'\1 ', text)


def _clean_wikilinks(text: str) -> str:
    """处理 [[wikilink]] 语法：[[概念名|别名]] -> 别名，[[概念名]] -> 概念名。"""
    text = re.sub(r'\[\[([^|\]]+)\|([^\]]+)\]\]', r'\2', text)
    text = re.sub(r'\[\[([^\]]+)\]\]', r'\1', text)
    return text


def _parse_frontmatter(text: str):
    """解析 YAML frontmatter，返回 (frontmatter_dict, body_text)。

    对格式不完整的 YAML（如未闭合标签）做容错处理，确保不阻塞索引。
    """
    if not text.startswith('---'):
        return {}, text
    end_idx = text.find('---', 3)
    if end_idx == -1:
        return {}, text
    fm_text = text[3:end_idx].strip()
    body = text[end_idx + 3:].strip()
    try:
        frontmatter = yaml.safe_load(fm_text) or {}
        return frontmatter, body
    except yaml.YAMLError:
        # 格式不完整（如未闭合标签），降级：只取 title（从文件首行或文件名）
        logger.debug("YAML frontmatter 解析降级（格式不完整）")
        # 尝试通过正则提取 title
        import re as _re
        title_match = _re.search(r'^title:\s*(.+?)$', fm_text, _re.MULTILINE)
        if title_match:
            return {'title': title_match.group(1).strip().strip('"\'')}, body
        return {}, body


class KnowledgeReader:
    """内嵌知识库读取器。

    用法:
        reader = KnowledgeReader("data/knowledge/concepts")
        reader.initialize()
        results = reader.match("背驰中枢")
    """

    def __init__(self, knowledge_dir: Optional[str] = None, db_path: Optional[str] = None):
        if knowledge_dir is None:
            data_dir = os.getenv('DATA_DIR')
            if data_dir:
                knowledge_dir = str(Path(data_dir) / 'knowledge/concepts')
            else:
                # 相对于项目根目录
                knowledge_dir = str(Path(__file__).resolve().parent.parent.parent.parent / 'data' / 'knowledge' / 'concepts')
        self._knowledge_dir = Path(knowledge_dir)
        self._db_path = db_path or ":memory:"
        self._db: Optional[sqlite3.Connection] = None
        self._initialized = False
        self._file_snapshot: Dict[str, float] = {}  # file_path → mtime

    def initialize(self) -> None:
        """扫描并索引知识库文件。可安全重复调用（已初始化时跳过）。"""
        if self._initialized:
            return

        start = __import__('time').time()
        self._db = sqlite3.connect(self._db_path, check_same_thread=False)
        self._db.execute("PRAGMA journal_mode=WAL")
        self._db.execute("PRAGMA synchronous=OFF")  # 批量索引加速

        self._db.execute("""
            CREATE VIRTUAL TABLE IF NOT EXISTS knowledge_fts USING fts5(
                title, content, tags,
                tokenize='unicode61'
            )
        """)

        self._db.execute("""
            CREATE TABLE IF NOT EXISTS knowledge_meta (
                file_path TEXT PRIMARY KEY,
                doc_type TEXT,
                file_size INTEGER DEFAULT 0,
                indexed_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)

        # 检查是否需要索引（文件数变化时全量重建）
        meta_count = self._db.execute("SELECT COUNT(*) FROM knowledge_meta").fetchone()[0]
        file_count = len(list(self._knowledge_dir.glob("*.md")))
        if meta_count < file_count:
            self._rebuild_index()

        self._initialized = True
        self._snapshot_files()
        elapsed = __import__('time').time() - start
        logger.info(f"KnowledgeReader 初始化完成 ({file_count} 文件, {elapsed*1000:.0f}ms)")

    def _rebuild_index(self) -> None:
        """全量重建 FTS5 索引。"""
        self._db.execute("DELETE FROM knowledge_fts")
        self._db.execute("DELETE FROM knowledge_meta")

        files = sorted(self._knowledge_dir.glob("*.md"))
        for file_path in files:
            self._index_file(file_path)

    def _index_file(self, file_path: Path) -> None:
        """索引单个概念文件。"""
        try:
            text = file_path.read_text(encoding='utf-8')
        except Exception:
            return

        frontmatter, body = _parse_frontmatter(text)
        body_clean = _clean_wikilinks(body)

        title = frontmatter.get("title", file_path.stem)
        doc_type = frontmatter.get("type", "concept")
        tags_list: list = frontmatter.get("tags", [])

        # FTS5 索引时对 CJK 做空格处理
        title_idx = _cjk_spaced(title)
        content_idx = _cjk_spaced(body_clean)
        tags_idx = " ".join(tags_list)

        self._db.execute(
            "INSERT INTO knowledge_fts(title, content, tags) VALUES (?, ?, ?)",
            (title_idx, content_idx, tags_idx),
        )
        self._db.execute(
            "INSERT INTO knowledge_meta(file_path, doc_type, file_size) VALUES (?, ?, ?)",
            (str(file_path), doc_type, len(text)),
        )

    def match(self, keywords: str, top_k: int = 3) -> List[Dict]:
        """查询知识库，返回匹配的概念内容。

        Args:
            keywords: 查询关键词（如"背驰 中枢 买点"）
            top_k: 最多返回条数

        Returns:
            [{title, content, tags, relevance, doc_type}, ...]
        """
        self.initialize()
        self._check_and_reload()

        if not keywords.strip():
            return []

        # 对查询词也做 CJK 空格处理
        query_terms = _cjk_spaced(keywords).strip()
        # 用空格分隔的词默认 AND 查询
        query = " AND ".join(query_terms.split())

        try:
            rows = self._db.execute(
                """SELECT title, content, tags, rank
                   FROM knowledge_fts
                   WHERE knowledge_fts MATCH ?
                   ORDER BY rank
                   LIMIT ?""",
                (query, top_k),
            ).fetchall()
        except sqlite3.OperationalError:
            logger.debug(f"FTS5 查询语法错误: {query}")
            return []

        results = []
        for title_idx, content_idx, tags, rank in rows:
            # 从索引格式恢复可读文本（去除 CJK 空格）
            title = re.sub(r'([\u4e00-\u9fff]) ', r'\1', title_idx)
            # 截取前 300 字作为摘要
            raw_content = re.sub(r'([\u4e00-\u9fff]) ', r'\1', content_idx)
            snippet = raw_content[:300]
            results.append({
                "title": title,
                "content": snippet,
                "tags": tags.split() if tags else [],
                "relevance": round(-float(rank), 4) if rank else 0.0,
            })

        return results

    def match_by_tags(self, tags: List[str], top_k: int = 5) -> List[Dict]:
        """按标签查询知识条目。"""
        self.initialize()
        if not tags:
            return []

        placeholders = ",".join("?" for _ in tags)
        rows = self._db.execute(
            f"""SELECT km.file_path, km.doc_type, km.file_size
                FROM knowledge_meta km
                WHERE km.file_path IN (
                    SELECT file_path FROM knowledge_meta
                    WHERE doc_type IN (SELECT value FROM json_each(?))
                )
                LIMIT ?""",
            (tags, top_k),
        ).fetchall()
        return [{"file_path": r[0], "doc_type": r[1], "file_size": r[2]} for r in rows]

    def get_stats(self) -> Dict:
        """返回知识库统计信息。"""
        self.initialize()
        total_files = self._db.execute("SELECT COUNT(*) FROM knowledge_meta").fetchone()[0]
        total_size = self._db.execute("SELECT COALESCE(SUM(file_size), 0) FROM knowledge_meta").fetchone()[0]
        return {
            "total_files": total_files,
            "total_size_bytes": total_size,
            "total_size_kb": round(total_size / 1024, 1),
        }

    def reload(self) -> None:
        """强制重建索引（供外部调用）。"""
        self._initialized = False
        self.initialize()

    def _snapshot_files(self) -> None:
        """记录当前文件列表及 mtime 快照。"""
        self._file_snapshot = {}
        for fp in self._knowledge_dir.glob("*.md"):
            try:
                self._file_snapshot[str(fp)] = fp.stat().st_mtime
            except Exception:
                pass

    def _check_and_reload(self) -> None:
        """检查文件是否有变更，有则自动重建索引。"""
        changed = False
        # 检查文件数变化
        current_files = {str(fp): fp.stat().st_mtime for fp in self._knowledge_dir.glob("*.md") if fp.exists()}
        if set(current_files.keys()) != set(self._file_snapshot.keys()):
            changed = True
        else:
            for fp, mtime in current_files.items():
                if abs(mtime - self._file_snapshot.get(fp, 0)) > 0.001:
                    changed = True
                    break
        if changed:
            logger.info("知识库文件变更，自动重建 FTS5 索引")
            self._rebuild_index()
            self._snapshot_files()


# 模块级单例
_knowledge_reader: Optional[KnowledgeReader] = None


def get_knowledge_reader(knowledge_dir: Optional[str] = None, db_path: Optional[str] = None) -> KnowledgeReader:
    """获取/初始化全局 KnowledgeReader 单例。"""
    global _knowledge_reader
    if _knowledge_reader is None:
        _knowledge_reader = KnowledgeReader(
            knowledge_dir=knowledge_dir,
            db_path=db_path,
        )
    return _knowledge_reader
