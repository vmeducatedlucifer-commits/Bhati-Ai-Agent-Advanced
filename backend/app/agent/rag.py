"""Codebase Vector RAG and Semantic Intelligence Engine.

Provides ultra-fast semantic code search over workspace files without needing heavy external vector databases,
making it 100% compatible with Render's 512MB RAM free tier.
"""

from __future__ import annotations

import math
import os
import re
from collections import Counter
from pathlib import Path
from typing import Any

from app.core.logging import get_logger

log = get_logger("app.agent.rag")

IGNORE_DIRS = {
    "node_modules", ".venv", "venv", "__pycache__", ".git", "dist", ".vite",
    ".pytest_cache", ".next", ".cache", "build", "data"
}

IGNORE_EXTS = {
    ".png", ".jpg", ".jpeg", ".gif", ".webp", ".ico", ".pdf", ".zip", ".tar", ".gz", ".db", ".sqlite3"
}


class CodeSnippet:
    def __init__(self, path: str, start_line: int, end_line: int, content: str):
        self.path = path
        self.start_line = start_line
        self.end_line = end_line
        self.content = content
        self.tokens = self._tokenize(content + " " + path)

    @staticmethod
    def _tokenize(text: str) -> list[str]:
        # Split CamelCase and snake_case into words
        words = re.findall(r"[A-Z]?[a-z]+|[A-Z]+(?=[A-Z][a-z]|\d|\b)|[a-zA-Z0-9]+", text)
        return [w.lower() for w in words if len(w) > 1]


class LightweightRAG:
    def __init__(self, workspace_path: str):
        self.workspace_path = Path(workspace_path)
        self.snippets: list[CodeSnippet] = []
        self.doc_freqs: Counter[str] = Counter()
        self.total_docs = 0

    def index_workspace(self) -> int:
        """Scan workspace text files and split into semantic chunks."""
        self.snippets.clear()
        self.doc_freqs.clear()

        if not self.workspace_path.exists():
            return 0

        for root, dirs, files in os.walk(self.workspace_path):
            dirs[:] = [d for d in dirs if d not in IGNORE_DIRS]
            for file in files:
                ext = Path(file).suffix.lower()
                if ext in IGNORE_EXTS:
                    continue

                full_path = Path(root) / file
                rel_path = str(_file_path_relative := full_path.relative_to(self.workspace_path))

                try:
                    text = full_path.read_text(encoding="utf-8", errors="ignore")
                    lines = text.splitlines()
                    if not lines:
                        continue

                    # Chunk by 40 lines
                    chunk_size = 40
                    overlap = 10
                    for i in range(0, len(lines), chunk_size - overlap):
                        chunk_lines = lines[i : i + chunk_size]
                        chunk_content = "\n".join(chunk_lines)
                        if not chunk_content.strip():
                            continue

                        snippet = CodeSnippet(rel_path, i + 1, i + len(chunk_lines), chunk_content)
                        self.snippets.append(snippet)

                        # Update doc frequencies for BM25
                        unique_tokens = set(snippet.tokens)
                        for token in unique_tokens:
                            self.doc_freqs[token] += 1

                except Exception:
                    pass

        self.total_docs = len(self.snippets)
        log.info("Indexed %d chunks across workspace: %s", self.total_docs, self.workspace_path)
        return self.total_docs

    def search(self, query: str, top_k: int = 5) -> list[dict[str, Any]]:
        """Rank code chunks using BM25 relevance scoring."""
        if not self.snippets:
            self.index_workspace()

        query_tokens = CodeSnippet._tokenize(query)
        if not query_tokens or self.total_docs == 0:
            return []

        scores: list[tuple[float, CodeSnippet]] = []

        k1 = 1.5
        b = 0.75
        avg_doc_len = sum(len(s.tokens) for s in self.snippets) / max(1, self.total_docs)

        for snippet in self.snippets:
            score = 0.0
            doc_len = len(snippet.tokens)
            doc_counts = Counter(snippet.tokens)

            for term in query_tokens:
                if term not in doc_counts:
                    continue

                tf = doc_counts[term]
                df = self.doc_freqs.get(term, 0)
                # BM25 IDF
                idf = math.log((self.total_docs - df + 0.5) / (df + 0.5) + 1.0)
                # BM25 TF formula
                num = tf * (k1 + 1)
                denom = tf + k1 * (1 - b + b * (doc_len / avg_doc_len))
                score += idf * (num / denom)

                # Bonus points if the term matches the file path
                if term in snippet.path.lower():
                    score += 2.0

            if score > 0:
                scores.append((score, snippet))

        scores.sort(key=lambda x: x[0], reverse=True)

        results = []
        for score, snip in scores[:top_k]:
            results.append({
                "score": round(score, 3),
                "path": snip.path,
                "start_line": snip.start_line,
                "end_line": snip.end_line,
                "content": snip.content,
            })

        return results
