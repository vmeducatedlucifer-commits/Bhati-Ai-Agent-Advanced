"""Streaming and resilient chat client for OpenAI-compatible, Anthropic, and custom AI Proxies.

Supports:
- Standard OpenAI & Anthropic API
- Custom Proxies (Bypass OpenAI, Venice AI, Uncensored Proxies, Ollama, OpenRouter, DeepSeek, Groq, LM Studio)
- Auto-fallback for Render.com free tier cold starts (502/503/504 automatic retry with backoff)
- Fallback for proxies that reject stream_options or structured tools
- Text-embedded tool-call salvage for models/proxies that return JSON tool calls in markdown text
"""

from __future__ import annotations

import asyncio
import json
import re
from collections.abc import AsyncIterator
from typing import Any

import httpx

from app.core.config import settings
from app.core.logging import get_logger
from app.llm.types import Completion, Delta, LLMError, ToolCall, Usage

log = get_logger("app.llm")


class _ToolCallAccumulator:
    """Reassembles OpenAI streaming tool-call fragments keyed by index."""

    def __init__(self) -> None:
        self._by_index: dict[int, dict[str, str]] = {}

    def add(self, fragment: dict[str, Any]) -> None:
        idx = fragment.get("index", 0)
        slot = self._by_index.setdefault(idx, {"id": "", "name": "", "arguments": ""})
        if fragment.get("id"):
            slot["id"] = fragment["id"]
        fn = fragment.get("function") or {}
        if fn.get("name"):
            slot["name"] = fn["name"]
        if fn.get("arguments"):
            slot["arguments"] += fn["arguments"]

    def finish(self) -> list[ToolCall]:
        calls: list[ToolCall] = []
        for idx in sorted(self._by_index):
            slot = self._by_index[idx]
            if not slot["name"]:
                continue
            raw = slot["arguments"] or "{}"
            try:
                args = json.loads(raw)
            except json.JSONDecodeError:
                args = _salvage_json(raw)
            calls.append(
                ToolCall(
                    id=slot["id"] or f"call_{idx}",
                    name=slot["name"],
                    arguments=args if isinstance(args, dict) else {"value": args},
                    raw_arguments=raw,
                )
            )
        return calls


def _salvage_json(raw: str) -> dict[str, Any]:
    """Models occasionally emit truncated or double-encoded argument blobs."""
    raw = raw.strip()
    if not raw:
        return {}
    for candidate in (raw, raw + "}", raw + '"}', raw.rstrip(",") + "}", raw + '"}', raw + '"}'):
        try:
            parsed = json.loads(candidate)
            if isinstance(parsed, dict):
                return parsed
        except json.JSONDecodeError:
            continue
    # Attempt to extract key-value pairs with regex as last resort
    return {}


def _extract_markdown_tool_calls(text: str, tools: list[dict[str, Any]] | None) -> list[ToolCall]:
    """Extract tool calls if a model outputs them in markdown or text instead of structured format."""
    if not text or not tools:
        return []
    valid_names = {t["function"]["name"] for t in tools}
    extracted: list[ToolCall] = []

    # Pattern 1: ```json { "name": "...", "arguments": { ... } } ```
    json_blocks = re.findall(r"```(?:json)?\s*([\s\S]*?)\s*```", text)
    for block in json_blocks:
        block = block.strip()
        try:
            parsed = json.loads(block)
            if isinstance(parsed, dict) and parsed.get("name") in valid_names:
                args = parsed.get("arguments") or parsed.get("parameters") or {}
                if isinstance(args, str):
                    try:
                        args = json.loads(args)
                    except Exception:
                        args = {"value": args}
                extracted.append(
                    ToolCall(
                        id=f"call_txt_{len(extracted)}",
                        name=parsed["name"],
                        arguments=args if isinstance(args, dict) else {"value": args},
                        raw_arguments=json.dumps(args),
                    )
                )
            elif isinstance(parsed, list):
                for item in parsed:
                    if isinstance(item, dict) and item.get("name") in valid_names:
                        args = item.get("arguments") or item.get("parameters") or {}
                        extracted.append(
                            ToolCall(
                                id=f"call_txt_{len(extracted)}",
                                name=item["name"],
                                arguments=args if isinstance(args, dict) else {"value": args},
                                raw_arguments=json.dumps(args),
                            )
                        )
        except Exception:
            continue

    # Pattern 2: Tool: tool_name({ ... }) or Action: tool_name
    if not extracted:
        action_matches = re.finditer(r"(?:Tool|Action|Function):\s*([a-zA-Z0-9_-]+)\s*(?:[\r\n]+(?:Arguments|Parameters|Args):\s*({[\s\S]*?}))?", text)
        for match in action_matches:
            name = match.group(1).strip()
            if name in valid_names:
                raw_args = match.group(2) or "{}"
                try:
                    args = json.loads(raw_args)
                except Exception:
                    args = _salvage_json(raw_args)
                extracted.append(
                    ToolCall(
                        id=f"call_txt_{len(extracted)}",
                        name=name,
                        arguments=args if isinstance(args, dict) else {},
                        raw_arguments=raw_args,
                    )
                )

    return extracted


def _create_http_client(timeout: int) -> httpx.AsyncClient:
    """Safely initialize an AsyncClient with HTTP/2 and standard keep-alive."""
    limits = httpx.Limits(max_keepalive_connections=20, max_connections=50, keepalive_expiry=60.0)
    try:
        import h2  # noqa: F401
        return httpx.AsyncClient(timeout=timeout, http2=True, limits=limits)
    except ImportError:
        return httpx.AsyncClient(timeout=timeout, limits=limits)


# A silent SSE stream is the classic "stuck agent": connection open, zero
# bytes, spinner forever. Any gap longer than this is treated as a stall and
# retried like a 502 — so a stall always ends in progress or a VISIBLE error,
# never an eternal hang. (Normal token gaps are seconds; first-token waits on
# cold proxies can approach a minute, hence the generous budget.)
STALL_TIMEOUT_S = 120


async def _pump_sse_lines(response: httpx.Response, queue: asyncio.Queue) -> None:
    """Forward response.aiter_lines() into a queue for stall-timed reading.

    The pump task is disposable: callers cancel it on stall and await it only
    for cleanup, so its CancelledError can never leak into the caller's task.
    """
    try:
        async for line in response.aiter_lines():
            await queue.put(line)
    except asyncio.CancelledError:
        raise
    except Exception as exc:
        await queue.put(exc)
    finally:
        await queue.put(None)


class LLMClient:
    def __init__(
        self,
        *,
        base_url: str,
        api_key: str,
        kind: str = "openai",
        extra_headers: dict[str, str] | None = None,
        timeout: int | None = None,
    ):
        raw_url = (base_url or settings.DEFAULT_LLM_BASE_URL).rstrip("/")
        if kind == "openai" and raw_url and not raw_url.endswith(("/v1", "/v2", "/api", "/api/v1")):
            # Automatically append /v1 for OpenAI proxies if omitted
            raw_url = f"{raw_url}/v1"
        self.base_url = raw_url
        self.api_key = api_key or settings.DEFAULT_LLM_API_KEY
        self.kind = kind
        self.extra_headers = extra_headers or {}
        self.timeout = timeout or settings.LLM_TIMEOUT_SECONDS

    # ---- headers ---------------------------------------------------------

    def _headers(self) -> dict[str, str]:
        headers = {
            "Content-Type": "application/json",
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36 BhatiAiAgent/2.0",
            "Accept": "application/json, text/event-stream, */*",
            "Accept-Language": "en-US,en;q=0.9",
            **self.extra_headers,
        }
        if self.kind == "anthropic":
            headers["x-api-key"] = self.api_key
            headers.setdefault("anthropic-version", "2023-06-01")
        elif self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        return headers

    # ---- public API ------------------------------------------------------

    async def stream(
        self,
        *,
        model: str,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
        temperature: float = 0.3,
        max_tokens: int | None = None,
    ) -> AsyncIterator[Delta]:
        if self.kind == "anthropic":
            async for delta in self._stream_anthropic(
                model=model, messages=messages, tools=tools,
                temperature=temperature, max_tokens=max_tokens,
            ):
                yield delta
        else:
            async for delta in self._stream_openai(
                model=model, messages=messages, tools=tools,
                temperature=temperature, max_tokens=max_tokens,
            ):
                yield delta

    async def complete(
        self,
        *,
        model: str,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
        temperature: float = 0.3,
        max_tokens: int | None = None,
    ) -> Completion:
        result = Completion(model=model)
        accumulator: list[ToolCall] = []
        async for delta in self.stream(
            model=model, messages=messages, tools=tools,
            temperature=temperature, max_tokens=max_tokens,
        ):
            if delta.kind == "text":
                result.content += delta.text
            elif delta.kind == "reasoning":
                result.reasoning += delta.text
            elif delta.kind == "tool_call" and delta.tool_call:
                accumulator.append(delta.tool_call)
            elif delta.kind == "usage" and delta.usage:
                result.usage = delta.usage
            elif delta.kind == "stop":
                result.finish_reason = delta.finish_reason

        # Salvage markdown tool calls if model didn't use native tool calling
        if not accumulator and tools:
            accumulator = _extract_markdown_tool_calls(result.content, tools)

        result.tool_calls = accumulator
        return result

    async def list_models(self) -> list[str]:
        if self.kind == "anthropic":
            return ["claude-3-5-sonnet-latest", "claude-3-5-haiku-latest", "claude-3-opus-latest"]
        try:
            async with httpx.AsyncClient(timeout=30) as client:
                r = await client.get(f"{self.base_url}/models", headers=self._headers())
                if r.status_code >= 400:
                    # Try without /v1 if attached
                    alt_url = self.base_url.rstrip("/v1") + "/models"
                    r = await client.get(alt_url, headers=self._headers())
                r.raise_for_status()
                data = r.json()
        except Exception as exc:
            log.warning("Could not list models from %s: %s", self.base_url, exc)
            return []
        items = data.get("data") if isinstance(data, dict) else data
        out: list[str] = []
        for item in items or []:
            if isinstance(item, str):
                out.append(item)
            elif isinstance(item, dict) and item.get("id"):
                out.append(item["id"])
        return sorted(set(out))

    # ---- openai stream with auto-retry and failover ----------------------

    async def _stream_openai(
        self, *, model, messages, tools, temperature, max_tokens
    ) -> AsyncIterator[Delta]:
        payload: dict[str, Any] = {
            "model": model,
            "messages": messages,
            "stream": True,
            "temperature": temperature,
            "stream_options": {"include_usage": True},
        }
        if tools:
            payload["tools"] = tools
            payload["tool_choice"] = "auto"
        if max_tokens:
            payload["max_tokens"] = max_tokens

        accumulator = _ToolCallAccumulator()
        finish_reason = ""
        full_text_accum = ""

        # Retry logic for Render cold start / temporary gateway errors
        max_retries = 3
        backoff = 2.0

        for attempt in range(max_retries):
            try:
                async with _create_http_client(self.timeout) as client:
                    async with client.stream(
                        "POST", f"{self.base_url}/chat/completions",
                        json=payload, headers=self._headers(),
                    ) as response:
                        if response.status_code in (502, 503, 504) and attempt < max_retries - 1:
                            log.warning(
                                "Proxy %s returned %d (possible cold start), retrying in %.1fs...",
                                self.base_url, response.status_code, backoff
                            )
                            await asyncio.sleep(backoff)
                            backoff *= 2
                            continue

                        if response.status_code == 400 and "stream_options" in payload:
                            # Some proxies fail when stream_options is included; retry without it
                            payload.pop("stream_options", None)
                            continue

                        if response.status_code >= 400:
                            body = (await response.aread()).decode(errors="replace")
                            if "<html" in body.lower():
                                raise LLMError(
                                    f"Proxy returned {response.status_code} (Cloudflare/Render instance starting or invalid endpoint). Check Base URL.",
                                    status=response.status_code,
                                    body=body[:300],
                                )
                            raise LLMError(
                                f"LLM returned {response.status_code}", status=response.status_code, body=body[:2000]
                            )

                        line_queue: asyncio.Queue = asyncio.Queue()
                        reader = asyncio.create_task(_pump_sse_lines(response, line_queue))
                        stalled = False
                        try:
                            while True:
                                try:
                                    item = await asyncio.wait_for(line_queue.get(), timeout=STALL_TIMEOUT_S)
                                except TimeoutError:
                                    log.warning(
                                        "LLM stream stalled (%ds without data) from %s — retrying...",
                                        STALL_TIMEOUT_S, self.base_url,
                                    )
                                    stalled = True
                                    break
                                if item is None:
                                    break
                                if isinstance(item, Exception):
                                    raise item
                                line = item
                                if not line or not line.startswith("data:"):
                                    continue
                                data = line[5:].strip()
                                if data == "[DONE]":
                                    break
                                try:
                                    chunk = json.loads(data)
                                except json.JSONDecodeError:
                                    continue

                                if usage := chunk.get("usage"):
                                    yield Delta(
                                        kind="usage",
                                        usage=Usage(
                                            prompt_tokens=usage.get("prompt_tokens", 0),
                                            completion_tokens=usage.get("completion_tokens", 0),
                                        ),
                                    )

                                for choice in chunk.get("choices") or []:
                                    delta = choice.get("delta") or {}
                                    if reasoning := (
                                        delta.get("reasoning_content") or delta.get("reasoning")
                                    ):
                                        yield Delta(kind="reasoning", text=str(reasoning))
                                    if content := delta.get("content"):
                                        if isinstance(content, list):
                                            content = "".join(
                                                b.get("text", "") for b in content if isinstance(b, dict)
                                            )
                                        if content:
                                            full_text_accum += content
                                            yield Delta(kind="text", text=content)
                                    for fragment in delta.get("tool_calls") or []:
                                        accumulator.add(fragment)
                                    if choice.get("finish_reason"):
                                        finish_reason = choice["finish_reason"]
                        finally:
                            # Fire-and-forget cancel on purpose: awaiting here
                            # would explode if this generator itself is being
                            # closed (await is illegal under GeneratorExit), and
                            # a cancelled pump task never logs warnings.
                            if not reader.done():
                                reader.cancel()
                        if stalled:
                            if attempt >= max_retries - 1:
                                raise LLMError(
                                    f"LLM stream stalled ({STALL_TIMEOUT_S}s without data) "
                                    f"from {self.base_url} after {max_retries} tries"
                                )
                            await asyncio.sleep(backoff)
                            backoff *= 2
                            continue
                        break
            except httpx.ConnectError as exc:
                if attempt < max_retries - 1:
                    await asyncio.sleep(backoff)
                    backoff *= 2
                    continue
                raise LLMError(f"Connection to {self.base_url} failed: {exc}") from exc
            except asyncio.CancelledError:
                raise

        parsed_calls = accumulator.finish()
        if not parsed_calls and tools and full_text_accum:
            # Check for markdown tool calls from uncensored / proxy models
            text_tool_calls = _extract_markdown_tool_calls(full_text_accum, tools)
            for tc in text_tool_calls:
                yield Delta(kind="tool_call", tool_call=tc)
        else:
            for call in parsed_calls:
                yield Delta(kind="tool_call", tool_call=call)

        yield Delta(kind="stop", finish_reason=finish_reason or "stop")

    # ---- anthropic stream ------------------------------------------------

    async def _stream_anthropic(
        self, *, model, messages, tools, temperature, max_tokens
    ) -> AsyncIterator[Delta]:
        system, converted = _to_anthropic_messages(messages)
        payload: dict[str, Any] = {
            "model": model,
            "messages": converted,
            "max_tokens": max_tokens or 8192,
            "temperature": temperature,
            "stream": True,
        }
        if system:
            payload["system"] = system
        if tools:
            payload["tools"] = [
                {
                    "name": t["function"]["name"],
                    "description": t["function"].get("description", ""),
                    "input_schema": t["function"].get("parameters", {"type": "object"}),
                }
                for t in tools
            ]

        blocks: dict[int, dict[str, Any]] = {}
        usage = Usage()

        async with _create_http_client(self.timeout) as client:
            async with client.stream(
                "POST", f"{self.base_url}/messages", json=payload, headers=self._headers()
            ) as response:
                if response.status_code >= 400:
                    body = (await response.aread()).decode(errors="replace")
                    if "<html" in body.lower():
                        raise LLMError(
                            f"Proxy blocked request with status {response.status_code}. Check Base URL.",
                            status=response.status_code,
                            body=body[:300],
                        )
                    raise LLMError(
                        f"LLM returned {response.status_code}", status=response.status_code, body=body[:2000]
                    )
                line_queue: asyncio.Queue = asyncio.Queue()
                reader = asyncio.create_task(_pump_sse_lines(response, line_queue))
                try:
                    while True:
                        try:
                            item = await asyncio.wait_for(line_queue.get(), timeout=STALL_TIMEOUT_S)
                        except TimeoutError:
                            raise LLMError(
                                f"LLM stream stalled ({STALL_TIMEOUT_S}s without data) from {self.base_url}"
                            )
                        if item is None:
                            break
                        if isinstance(item, Exception):
                            raise item
                        line = item
                        if not line.startswith("data:"):
                            continue
                        try:
                            event = json.loads(line[5:].strip())
                        except json.JSONDecodeError:
                            continue
                        etype = event.get("type")

                        if etype == "content_block_start":
                            blocks[event["index"]] = dict(event.get("content_block") or {})
                            blocks[event["index"]]["_json"] = ""
                        elif etype == "content_block_delta":
                            d = event.get("delta") or {}
                            if d.get("type") == "text_delta":
                                yield Delta(kind="text", text=d.get("text", ""))
                            elif d.get("type") == "thinking_delta":
                                yield Delta(kind="reasoning", text=d.get("thinking", ""))
                            elif d.get("type") == "input_json_delta":
                                blocks.setdefault(event["index"], {"_json": ""})
                                blocks[event["index"]]["_json"] += d.get("partial_json", "")
                        elif etype == "message_delta":
                            u = event.get("usage") or {}
                            usage.completion_tokens = u.get("output_tokens", usage.completion_tokens)
                        elif etype == "message_start":
                            u = (event.get("message") or {}).get("usage") or {}
                            usage.prompt_tokens = u.get("input_tokens", 0)
                finally:
                    # Fire-and-forget cancel (see OpenAI path): awaiting here
                    # would explode if this generator is being closed.
                    if not reader.done():
                        reader.cancel()

        for block in blocks.values():
            if block.get("type") == "tool_use":
                raw = block.get("_json") or "{}"
                try:
                    args = json.loads(raw) if raw.strip() else {}
                except json.JSONDecodeError:
                    args = _salvage_json(raw)
                yield Delta(
                    kind="tool_call",
                    tool_call=ToolCall(
                        id=block.get("id", "call"), name=block.get("name", ""),
                        arguments=args, raw_arguments=raw,
                    ),
                )
        yield Delta(kind="usage", usage=usage)
        yield Delta(kind="stop", finish_reason="stop")


def _to_anthropic_messages(messages: list[dict[str, Any]]) -> tuple[str, list[dict[str, Any]]]:
    system_parts: list[str] = []
    out: list[dict[str, Any]] = []
    for msg in messages:
        role = msg.get("role")
        if role == "system":
            system_parts.append(str(msg.get("content") or ""))
        elif role == "tool":
            out.append({
                "role": "user",
                "content": [{
                    "type": "tool_result",
                    "tool_use_id": msg.get("tool_call_id", ""),
                    "content": str(msg.get("content") or ""),
                }],
            })
        elif role == "assistant" and msg.get("tool_calls"):
            content: list[dict[str, Any]] = []
            if msg.get("content"):
                content.append({"type": "text", "text": msg["content"]})
            for tc in msg["tool_calls"]:
                fn = tc.get("function", {})
                try:
                    args = json.loads(fn.get("arguments") or "{}")
                except json.JSONDecodeError:
                    args = {}
                content.append({
                    "type": "tool_use", "id": tc.get("id", ""),
                    "name": fn.get("name", ""), "input": args,
                })
            out.append({"role": "assistant", "content": content})
        else:
            out.append({"role": role or "user", "content": str(msg.get("content") or "")})
    return "\n\n".join(system_parts), out
