"""Jupyter Notebook tool matching Claude Code NotebookEditTool."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from app.tools.base import ToolContext, ToolResult, boolean, integer, obj, string
from app.tools.registry import registry


@registry.tool(
    "notebook_edit",
    (
        "Edit, insert, replace, or delete cells in a Jupyter Notebook (.ipynb file). "
        "Supports markdown and code cells."
    ),
    obj(
        {
            "notebook_path": string("Path to the .ipynb file relative to workspace"),
            "cell_index": integer("0-based index of the cell to modify or insert at", default=0),
            "action": string("Action to perform", enum=["replace", "insert", "delete", "view"], default="replace"),
            "cell_type": string("Cell type if inserting or replacing", enum=["code", "markdown"], default="code"),
            "source": string("Content / source code of the cell", default=""),
        },
        ["notebook_path"],
    ),
    permission="write",
    group="files",
    mutating=True,
)
async def notebook_edit(
    ctx: ToolContext,
    notebook_path: string,
    cell_index: int = 0,
    action: str = "replace",
    cell_type: str = "code",
    source: str = "",
) -> ToolResult:
    try:
        raw_content = await ctx.sandbox.read_file(notebook_path)
        notebook: dict[str, Any] = json.loads(raw_content)
    except Exception as exc:
        if action == "insert":
            # Create fresh notebook structure
            notebook = {
                "cells": [],
                "metadata": {
                    "language_info": {"name": "python"},
                    "orig_nbformat": 4,
                },
                "nbformat": 4,
                "nbformat_minor": 5,
            }
        else:
            return ToolResult.error(f"Could not read notebook '{notebook_path}': {exc}")

    cells: list[dict[str, Any]] = notebook.get("cells", [])

    if action == "view":
        lines = [f"# Notebook: {notebook_path} ({len(cells)} cells)\n"]
        for idx, cell in enumerate(cells):
            ctype = cell.get("cell_type", "unknown")
            csrc = "".join(cell.get("source", []))
            lines.append(f"--- Cell [{idx}] ({ctype}) ---\n{csrc}\n")
        return ToolResult(content="\n".join(lines))

    if action == "delete":
        if not (0 <= cell_index < len(cells)):
            return ToolResult.error(f"Cell index {cell_index} out of bounds (total cells: {len(cells)})")
        deleted = cells.pop(cell_index)
        await ctx.sandbox.write_file(notebook_path, json.dumps(notebook, indent=2))
        return ToolResult(content=f"Deleted cell [{cell_index}] ({deleted.get('cell_type')})")

    source_lines = [line + "\n" for line in source.splitlines()]
    if source and not source.endswith("\n") and source_lines:
        source_lines[-1] = source_lines[-1].rstrip("\n")

    new_cell: dict[str, Any] = {
        "cell_type": cell_type,
        "metadata": {},
        "source": source_lines,
    }
    if cell_type == "code":
        new_cell["execution_count"] = None
        new_cell["outputs"] = []

    if action == "insert":
        idx = max(0, min(cell_index, len(cells)))
        cells.insert(idx, new_cell)
        action_desc = f"Inserted {cell_type} cell at [{idx}]"
    elif action == "replace":
        if not (0 <= cell_index < len(cells)):
            return ToolResult.error(f"Cell index {cell_index} out of bounds (total cells: {len(cells)})")
        cells[cell_index] = new_cell
        action_desc = f"Replaced cell [{cell_index}] with {cell_type} cell"
    else:
        return ToolResult.error(f"Unsupported action: {action}")

    notebook["cells"] = cells
    serialized = json.dumps(notebook, indent=2)
    await ctx.sandbox.write_file(notebook_path, serialized)
    return ToolResult(content=f"Successfully updated '{notebook_path}': {action_desc}")
