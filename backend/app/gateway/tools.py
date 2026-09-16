"""
Universal Tool Calling & Multi-Turn Message Serializer for Gemini Tunnel.
Supports Hermes Agent, Claude Code, Anthropic SDK, OpenAI SDK, Cursor, Cline, Roo Code, Aider.
"""
from __future__ import annotations

import json
import logging
import re
import uuid
from typing import Any, Dict, List, Optional, Tuple, Union

logger = logging.getLogger(__name__)


def format_tools_system_prompt(tools: List[Any]) -> str:
    """
    Format tools into a universal Hermes & Claude compatible tool specification
    with explicit multi-turn agent instructions.
    """
    if not tools:
        return ""

    tool_defs: List[Dict[str, Any]] = []
    for t in tools:
        if not isinstance(t, dict):
            continue
        if "function" in t and isinstance(t["function"], dict):
            fn = t["function"]
            tool_defs.append({
                "name": fn.get("name", ""),
                "description": fn.get("description", ""),
                "parameters": fn.get("parameters", {}),
            })
        elif "name" in t:
            tool_defs.append({
                "name": t.get("name", ""),
                "description": t.get("description", ""),
                "parameters": t.get("input_schema", t.get("parameters", {})),
            })

    if not tool_defs:
        return ""

    json_tools = json.dumps(tool_defs, indent=2)

    return f"""# TOOL CALLING INSTRUCTIONS & AVAILABLE TOOLS
You have access to the following tools:
<tools>
{json_tools}
</tools>

HOW TO CALL TOOLS:
When you need to call one or more tools, you MUST respond strictly using the following XML format:
<tool_call>
{{"name": "tool_name", "arguments": {{"param1": "value1"}}}}
</tool_call>

RULES:
1. Only call tools that are listed in the <tools> section above.
2. Ensure arguments strictly follow the JSON schema of each tool parameter.
3. DECISION RULE (critical): read the user's LATEST message. If ANY listed tool can help with it, you MUST emit a <tool_call> block — NEVER answer such a request directly instead of calling. Only when NO listed tool is relevant may you answer directly with no <tool_call> tags.
4. Brief reasoning text before the <tool_call> block is allowed, but the block itself must always be present when a tool applies.
5. When you receive a [Tool Result ...] message, use its output: call another tool or give the final answer.
6. NEVER repeat a tool call with the same name and arguments twice. If the result you need is already in the conversation, answer NOW instead of calling again.
7. One <tool_call> block per call. The JSON inside must be valid (double quotes, no trailing commas, no comments).

EXAMPLE — user asks "What is the weather in Paris?" and get_weather exists:
<tool_call>
{{"name": "get_weather", "arguments": {{"city": "Paris"}}}}
</tool_call>
"""


def extract_tool_calls_and_text(
    text: str, available_tools: Optional[List[Any]] = None
) -> Tuple[str, List[Dict[str, Any]]]:
    """
    Universally parse tool calls in Hermes (<tool_call>), Anthropic (<tool_use>),
    Markdown code fences, or raw JSON, and return clean user text and tool_calls.
    """
    if not text:
        return "", []

    tool_calls: List[Dict[str, Any]] = []
    cleaned = text

    tool_names = set()
    if available_tools:
        for t in available_tools:
            if isinstance(t, dict):
                if "function" in t and isinstance(t["function"], dict) and "name" in t["function"]:
                    tool_names.add(t["function"]["name"])
                elif "name" in t:
                    tool_names.add(t["name"])

    # 1. Hermes / Standard XML format: <tool_call>...</tool_call>
    hermes_pattern = re.compile(r"<tool_call>\s*([\s\S]*?)\s*</tool_call>", re.DOTALL)
    for match in hermes_pattern.finditer(text):
        raw_block = match.group(0)
        content = match.group(1).strip()
        cleaned = cleaned.replace(raw_block, "").strip()
        try:
            parsed = json.loads(content)
            if isinstance(parsed, list):
                for item in parsed:
                    name = item.get("name") or item.get("tool") or item.get("function")
                    args = item.get("arguments") or item.get("parameters") or item.get("input") or {}
                    if name:
                        tool_calls.append({
                            "id": f"call_{uuid.uuid4().hex[:12]}",
                            "type": "function",
                            "function": {
                                "name": name,
                                "arguments": args if isinstance(args, str) else json.dumps(args, separators=(",", ":")),
                            },
                        })
            elif isinstance(parsed, dict):
                name = parsed.get("name") or parsed.get("tool") or parsed.get("function")
                args = parsed.get("arguments") or parsed.get("parameters") or parsed.get("input") or {}
                if name:
                    tool_calls.append({
                        "id": f"call_{uuid.uuid4().hex[:12]}",
                        "type": "function",
                        "function": {
                            "name": name,
                            "arguments": args if isinstance(args, str) else json.dumps(args, separators=(",", ":")),
                        },
                    })
        except Exception:
            pass

    # 2. Anthropic style XML: <tool_use><name>NAME</name><input>JSON/TEXT</input></tool_use>
    anthropic_pattern = re.compile(r"<tool_use>\s*<name>(.*?)</name>\s*<input>([\s\S]*?)</input>\s*</tool_use>", re.DOTALL)
    for match in anthropic_pattern.finditer(cleaned):
        raw_block = match.group(0)
        name = match.group(1).strip()
        input_str = match.group(2).strip()
        cleaned = cleaned.replace(raw_block, "").strip()
        try:
            args = json.loads(input_str)
            args_str = json.dumps(args, separators=(",", ":"))
        except Exception:
            args_str = json.dumps({"input": input_str})
        tool_calls.append({
            "id": f"toolu_{uuid.uuid4().hex[:12]}",
            "type": "function",
            "function": {"name": name, "arguments": args_str},
        })

    # 3. Code fence blocks: ```tool_call ... ``` or ```json ... ``` (if matching known tool)
    fence_pattern = re.compile(r"```(?:tool_call|json)?\s*(\{[\s\S]*?\})\s*```", re.DOTALL)
    for match in fence_pattern.finditer(cleaned):
        raw_block = match.group(0)
        content = match.group(1).strip()
        try:
            parsed = json.loads(content)
            name = parsed.get("name") or parsed.get("tool") or parsed.get("function")
            if name and (not tool_names or name in tool_names):
                cleaned = cleaned.replace(raw_block, "").strip()
                args = parsed.get("arguments") or parsed.get("parameters") or parsed.get("input") or {}
                tool_calls.append({
                    "id": f"call_{uuid.uuid4().hex[:12]}",
                    "type": "function",
                    "function": {
                        "name": name,
                        "arguments": args if isinstance(args, str) else json.dumps(args, separators=(",", ":")),
                    },
                })
        except Exception:
            pass

    return cleaned.strip(), tool_calls


def serialize_openai_messages(
    messages: List[Any],
    tools: Optional[List[Any]] = None,
    system_prompt: Optional[str] = None,
) -> str:
    """
    Serialize OpenAI message history (including system, user, assistant with tool_calls,
    and tool execution results) into an optimized prompt for Gemini.
    """
    parts: List[str] = []

    # 1. System Prompt and Tool instructions
    tool_instructions = format_tools_system_prompt(tools or [])
    all_systems = []
    if system_prompt:
        all_systems.append(system_prompt.strip())

    for m in messages:
        if isinstance(m, dict):
            role = m.get("role", "")
            content = m.get("content", "")
        else:
            role = getattr(m, "role", "")
            content = getattr(m, "content", "")

        if role == "system" and content:
            if isinstance(content, str):
                all_systems.append(content.strip())
            elif isinstance(content, list):
                for c in content:
                    if isinstance(c, dict) and c.get("type") == "text":
                        all_systems.append(c.get("text", "").strip())

    if tool_instructions:
        all_systems.append(tool_instructions)

    if all_systems:
        parts.append(f"# SYSTEM INSTRUCTIONS\n" + "\n\n".join(all_systems))

    # 2. Conversation History
    for m in messages:
        if isinstance(m, dict):
            role = m.get("role", "")
            content = m.get("content", "")
            tool_calls = m.get("tool_calls")
            tool_call_id = m.get("tool_call_id")
            name = m.get("name")
        else:
            role = getattr(m, "role", "")
            content = getattr(m, "content", "")
            tool_calls = getattr(m, "tool_calls", None)
            tool_call_id = getattr(m, "tool_call_id", None)
            name = getattr(m, "name", None)

        if role == "system":
            continue

        if role == "user":
            user_text = ""
            if isinstance(content, str):
                user_text = content
            elif isinstance(content, list):
                text_pieces = []
                for item in content:
                    if isinstance(item, str):
                        text_pieces.append(item)
                    elif isinstance(item, dict):
                        if item.get("type") == "text":
                            text_pieces.append(item.get("text", ""))
                        elif item.get("type") == "image_url":
                            text_pieces.append("[Image attached]")
                user_text = "\n".join(text_pieces)
            parts.append(f"User: {user_text}")

        elif role == "assistant":
            asst_text = ""
            if isinstance(content, str) and content:
                asst_text = content
            elif isinstance(content, list):
                text_pieces = [
                    item.get("text", "")
                    for item in content
                    if isinstance(item, dict) and item.get("type") == "text"
                ]
                asst_text = "\n".join(text_pieces)

            call_blocks = []
            if tool_calls:
                for tc in tool_calls:
                    fn = tc.get("function", {}) if isinstance(tc, dict) else getattr(tc, "function", {})
                    fn_name = fn.get("name", "") if isinstance(fn, dict) else getattr(fn, "name", "")
                    fn_args = fn.get("arguments", "{}") if isinstance(fn, dict) else getattr(fn, "arguments", "{}")
                    try:
                        args_obj = json.loads(fn_args) if isinstance(fn_args, str) else fn_args
                    except Exception:
                        args_obj = {"raw": str(fn_args)}
                    call_blocks.append(
                        f"<tool_call>\n{json.dumps({'name': fn_name, 'arguments': args_obj}, indent=2)}\n</tool_call>"
                    )

            full_asst = (asst_text + "\n" + "\n".join(call_blocks)).strip()
            parts.append(f"Assistant: {full_asst}")

        elif role in ("tool", "function"):
            tool_label = name or tool_call_id or "tool"
            tool_out = content if isinstance(content, str) else json.dumps(content)
            parts.append(f"[Tool Result for {tool_label}]:\n{tool_out}")

    return "\n\n".join(parts)


def serialize_anthropic_messages(
    messages: List[Any],
    tools: Optional[List[Any]] = None,
    system_prompt: Optional[Union[str, List[Any]]] = None,
) -> str:
    """
    Serialize Anthropic message structure (including tool_use, tool_result blocks,
    and system prompts) into an optimized prompt for Gemini.
    """
    parts: List[str] = []

    # 1. System Prompt & Tool definitions
    all_systems: List[str] = []
    if system_prompt:
        if isinstance(system_prompt, str):
            all_systems.append(system_prompt.strip())
        elif isinstance(system_prompt, list):
            for block in system_prompt:
                if isinstance(block, str):
                    all_systems.append(block.strip())
                elif isinstance(block, dict) and block.get("type") == "text":
                    all_systems.append(block.get("text", "").strip())

    tool_instructions = format_tools_system_prompt(tools or [])
    if tool_instructions:
        all_systems.append(tool_instructions)

    if all_systems:
        parts.append(f"# SYSTEM INSTRUCTIONS\n" + "\n\n".join(all_systems))

    # 2. Conversation Turns
    for m in messages:
        if isinstance(m, dict):
            role = m.get("role", "")
            content = m.get("content", "")
        else:
            role = getattr(m, "role", "")
            content = getattr(m, "content", "")

        if isinstance(content, str):
            parts.append(f"{role.capitalize()}: {content}")
        elif isinstance(content, list):
            turn_lines = []
            for block in content:
                if not isinstance(block, dict):
                    continue
                btype = block.get("type", "")
                if btype == "text":
                    turn_lines.append(block.get("text", ""))
                elif btype == "tool_use":
                    t_name = block.get("name", "")
                    t_input = block.get("input", {})
                    turn_lines.append(
                        f"<tool_call>\n{json.dumps({'name': t_name, 'arguments': t_input}, indent=2)}\n</tool_call>"
                    )
                elif btype == "tool_result":
                    tid = block.get("tool_use_id", "tool")
                    res_content = block.get("content", "")
                    if isinstance(res_content, list):
                        res_text = "\n".join(
                            b.get("text", "") for b in res_content if isinstance(b, dict) and b.get("type") == "text"
                        )
                    else:
                        res_text = str(res_content)
                    is_err = block.get("is_error", False)
                    status_str = " (Error)" if is_err else ""
                    turn_lines.append(f"[Tool Result for {tid}{status_str}]:\n{res_text}")
            parts.append(f"{role.capitalize()}: " + "\n".join(turn_lines))

    return "\n\n".join(parts)
