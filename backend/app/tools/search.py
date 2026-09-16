"""Code search: glob by name, grep by content."""

from __future__ import annotations

import shlex

from app.core.utils import truncate
from app.tools.base import ToolContext, ToolResult, boolean, integer, obj, string
from app.tools.registry import registry

PRUNE_DIRS = {"node_modules", ".git", "__pycache__", ".venv", "dist", "build", ".next", ".cache"}


def _glob_match(pattern: str, name: str) -> bool:
    """Simple glob matching: supports *, **, and ? patterns."""
    import fnmatch
    return fnmatch.fnmatch(name, pattern)


async def _native_glob(ctx: ToolContext, pattern: str, path: str, limit: int) -> list[str]:
    """Python-native recursive glob when shell find is unavailable (e.g. Windows)."""
    from fnmatch import fnmatch
    results: list[str] = []
    base_path = path or "."

    # Flatten directory tree
    queue = [base_path]
    visited: set[str] = set()
    while queue and len(results) < limit:
        current = queue.pop(0)
        if current in visited:
            continue
        visited.add(current)
        try:
            entries = await ctx.sandbox.list_dir(current)
        except Exception:
            continue
        for entry in entries:
            full = f"{current}/{entry.name}" if current != "." else entry.name
            if entry.is_dir:
                if entry.name not in PRUNE_DIRS:
                    queue.append(full)
            else:
                name = entry.name
                if pattern.startswith("**/"):
                    # Match against name portion only
                    if fnmatch(name, pattern[3:]) or fnmatch(full, pattern):
                        results.append(full)
                elif fnmatch(name, pattern.rsplit("/", 1)[-1]):
                    results.append(full)
    return results[:limit]


@registry.tool(
    "glob",
    "Find files by name pattern, e.g. `**/*.tsx` or `src/**/test_*.py`. Fast; use before reading.",
    obj(
        {
            "pattern": string("Glob pattern"),
            "path": string("Directory to search from", default=""),
            "limit": integer("Maximum matches", default=200),
        },
        ["pattern"],
    ),
    group="search",
)
async def glob(ctx: ToolContext, pattern: str, path: str = "", limit: int = 200):
    # Try native shell find first (faster on Linux/Docker)
    try:
        base = shlex.quote(path or ".")
        name = pattern.rsplit("/", 1)[-1]
        cmd = f"find {base} -type f -name {shlex.quote(name)} -print 2>/dev/null | head -n {limit}"
        res = await ctx.sandbox.exec(cmd, timeout=60)
        if res.exit_code == 0:
            matches = [m for m in res.stdout.splitlines() if m.strip()]
            if matches:
                return ToolResult(
                    content=f"{len(matches)} match(es) for `{pattern}`:\n" + "\n".join(matches),
                    display={"kind": "list", "title": f"glob {pattern}", "items": matches},
                )
    except Exception:
        pass

    # Fallback: Python-native glob for Windows or when find is unavailable
    matches = await _native_glob(ctx, pattern, path, limit)
    if not matches:
        return ToolResult(content=f"No files matching `{pattern}`")
    return ToolResult(
        content=f"{len(matches)} match(es) for `{pattern}`:\n" + "\n".join(matches),
        display={"kind": "list", "title": f"glob {pattern}", "items": matches},
    )


@registry.tool(
    "grep",
    (
        "Search file contents with a regular expression. Returns `path:line:match`. "
        "Use `glob_filter` to restrict to a file type."
    ),
    obj(
        {
            "pattern": string("Regular expression"),
            "path": string("Directory to search (a single file path works too)", default=""),
            "glob_filter": string("Restrict to files matching this glob, e.g. *.ts", default=""),
            "case_insensitive": boolean("Ignore case", default=False),
            "context": integer("Lines of context around each match", default=0),
            "limit": integer("Maximum matching lines", default=200),
        },
        ["pattern"],
    ),
    group="search",
)
async def grep(
    ctx: ToolContext,
    pattern: str,
    path: str = "",
    glob_filter: str = "",
    case_insensitive: bool = False,
    context: int = 0,
    limit: int = 200,
):
    import re as re_mod

    re_flags = re_mod.IGNORECASE if case_insensitive else 0
    try:
        regex = re_mod.compile(pattern, re_flags)
    except re_mod.error as exc:
        return ToolResult.error(f"Invalid regex pattern: {exc}")

    # Models often pass a FILE in `path` although it usually means a directory.
    # Searching "inside" a file path previously scanned zero files and reported
    # "No matches" — search that file directly instead.
    if path and not glob_filter:
        try:
            entries = await ctx.sandbox.list_dir(path)
        except Exception:
            entries = None
        if not entries:
            try:
                single = await ctx.sandbox.read_file(path)
            except Exception:
                single = None
            if single is not None:
                hits = [
                    f"{path}:{i}:{line.strip()}"
                    for i, line in enumerate(single.splitlines(), 1)
                    if regex.search(line)
                ][:limit]
                if hits:
                    return ToolResult(
                        content="\n".join(hits),
                        display={"kind": "list", "title": f"grep {pattern}", "items": hits},
                    )
                return ToolResult(content=f"No matches for `{pattern}`")

    base = shlex.quote(path or ".")
    flags_str = "-n --color=never"
    if case_insensitive:
        flags_str += " -i"
    if context:
        flags_str += f" -C {int(context)}"

    # Try shell ripgrep or grep first
    try:
        has_rg = await ctx.sandbox.exec("command -v rg >/dev/null 2>&1 && echo yes", timeout=15)
        if "yes" in has_rg.stdout:
            cmd = f"rg {flags_str} {shlex.quote(pattern)} {base}"
            if glob_filter:
                cmd += f" --glob {shlex.quote(glob_filter)}"
            cmd += f" | head -n {limit}"
        else:
            include = f"--include={shlex.quote(glob_filter)}" if glob_filter else ""
            cmd = (
                f"grep -r {flags_str} {include} --exclude-dir=node_modules --exclude-dir=.git "
                f"--exclude-dir=__pycache__ --exclude-dir=.venv {shlex.quote(pattern)} {base} | head -n {limit}"
            )

        res = await ctx.sandbox.exec(cmd, timeout=90)
        if res.exit_code == 0:
            out = res.stdout.strip()
            if out:
                return ToolResult(
                    content=truncate(out, 20_000),
                    display={"kind": "list", "title": f"grep {pattern}", "items": out.splitlines()[:limit]},
                )
    except Exception:
        pass

    # Fallback: Python-native grep for Windows or when shell grep is unavailable
    # (regex already compiled + validated above).
    results: list[str] = []
    all_files = await _native_glob(ctx, glob_filter or "**/*", path, limit=500)
    for file_path in all_files[:200]:
        try:
            content = await ctx.sandbox.read_file(file_path)
        except Exception:
            continue
        for i, line in enumerate(content.splitlines(), 1):
            if regex.search(line):
                results.append(f"{file_path}:{i}:{line.strip()}")
                if len(results) >= limit:
                    break
        if len(results) >= limit:
            break

    if not results:
        return ToolResult(content=f"No matches for `{pattern}`")
    return ToolResult(
        content=truncate("\n".join(results), 20_000),
        display={"kind": "list", "title": f"grep {pattern}", "items": results},
    )


@registry.tool(
    "codebase_search",
    (
        "Semantic vector/BM25 search over the entire codebase. Finds relevant code snippets "
        "by concept or functionality (e.g. 'find where JWT tokens are parsed' or 'auth flow')."
    ),
    obj(
        {
            "query": string("Natural language or concept query to search for"),
            "top_k": integer("Maximum relevant code chunks to return", default=5),
        },
        ["query"],
    ),
    group="search",
)
async def codebase_search(ctx: ToolContext, query: str, top_k: int = 5):
    from app.agent.rag import LightweightRAG
    rag = LightweightRAG(ctx.workspace)
    results = rag.search(query, top_k=top_k)

    if not results:
        return ToolResult(content=f"No codebase matches found for query `{query}`")

    output_lines = [f"Found {len(results)} relevant code snippet(s) for query `{query}`:\n"]
    for r in results:
        output_lines.append(
            f"--- {r['path']} (lines {r['start_line']}-{r['end_line']}, relevance score: {r['score']}) ---\n"
            f"```\n{r['content']}\n```\n"
        )

    return ToolResult(
        content="\n".join(output_lines),
        display={"kind": "search", "query": query, "results": results},
    )
