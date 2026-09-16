"""Embedded model gateway HTTP server — loopback-only, agent-only.

Exposes the MINIMUM surface the agent needs:
  POST /v1/chat/completions   OpenAI-compatible (streaming + tool calls + usage)
  GET  /v1/models             the two builtin models only
  GET  /health                liveness, no version/schema disclosure

Everything else from the standalone proxy (playground, sessions, pool,
Anthropic/Gemini-native endpoints, workspace browser, tag executor) is
deliberately NOT included: smaller surface, nothing to fingerprint.

Auth: `Authorization: Bearer <GATEWAY_SHARED_SECRET>`, constant-time compare.
When no secret is configured (local dev only) requests are still confined to
loopback by the bind address (default 127.0.0.1 — see start.sh).
"""
from __future__ import annotations

import asyncio
import hmac
import json
import logging
import time
import uuid
from contextlib import asynccontextmanager
from typing import Any, AsyncIterator, Dict, List, Optional, Union

from fastapi import Depends, FastAPI, Header
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import BaseModel, Field

from .config import BUILTIN_MODELS, settings
from .tools import extract_tool_calls_and_text, serialize_openai_messages
from .tunnel import GeminiTunnel, resolve_model, session_pool

logger = logging.getLogger("app.gateway")
tunnel = GeminiTunnel()

# Markers that open a tool-call block. Narration BEFORE the first marker
# streams live; everything from the marker on is held back until parsed —
# SSE cannot retract, so partial XML must never hit the wire.
_TOOL_MARKERS = ("<tool_call", "<tool_use")


def _first_tool_marker(text: str) -> int:
    positions = [text.find(m) for m in _TOOL_MARKERS]
    positions = [p for p in positions if p != -1]
    return min(positions) if positions else -1


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Pre-warm tunnel sessions in the background so the first real request
    rarely pays the ~5-15s browser warm-up probe (the main 'stuck, then burst'
    complaint). Startup itself never waits for warming."""
    async def _prewarm():
        try:
            for _ in range(min(3, settings.session_pool_size)):
                await session_pool.get_session(force_new=True)
        except Exception as exc:
            logger.warning(f"Gateway session pre-warm failed (will warm on demand): {exc}")

    task = asyncio.create_task(_prewarm())
    try:
        yield
    finally:
        task.cancel()
        try:
            await task
        except (asyncio.CancelledError, Exception):
            pass
        try:
            await tunnel.aclose()
        except Exception:
            pass


async def require_agent(authorization: Optional[str] = Header(None)) -> str:
    """Only the agent (shared secret) may call.

    The agent always sends `Authorization: Bearer <secret>`. Comparison is
    constant-time. No secret configured (local dev only) still leaves the
    server confined to loopback via the bind address — prod refuses to boot
    without a secret (see app.main lifespan guard).
    """
    from fastapi import HTTPException

    secret = settings.shared_secret
    if not secret:
        return "local"
    token = ""
    if authorization and authorization.lower().startswith("bearer "):
        token = authorization[7:].strip()
    if token and hmac.compare_digest(token, secret):
        return "agent"
    raise HTTPException(status_code=403, detail="Forbidden")


class ChatMessage(BaseModel):
    role: str
    content: Union[str, List[Any], None] = ""
    name: Optional[str] = None
    tool_calls: Optional[List[Any]] = None
    tool_call_id: Optional[str] = None


class ChatCompletionRequest(BaseModel):
    model: str = Field(default_factory=lambda: settings.default_model)
    messages: List[ChatMessage]
    temperature: Optional[float] = 0.7
    max_tokens: Optional[int] = None
    max_completion_tokens: Optional[int] = None
    stream: bool = False
    tools: Optional[List[Any]] = None
    tool_choice: Optional[Any] = None
    functions: Optional[List[Any]] = None
    function_call: Optional[Any] = None
    system: Optional[Union[str, List[Any]]] = None


app = FastAPI(
    title="Embedded Gateway",
    version="1.0.0",
    docs_url=None,
    redoc_url=None,
    openapi_url=None,
    lifespan=lifespan,
)


def _sse_text_chunk(completion_id: str, created_ts: int, model_name: str, text: str) -> str:
    return f"data: {json.dumps({
        'id': completion_id,
        'object': 'chat.completion.chunk',
        'created': created_ts,
        'model': model_name,
        'choices': [{'index': 0, 'delta': {'content': text}, 'finish_reason': None}],
    })}\n\n"


# Proxies (Render/Cloudflare/nginx) must not buffer the event stream —
# buffering turns live tokens into one end-of-response burst.
SSE_HEADERS = {"Cache-Control": "no-cache", "X-Accel-Buffering": "no"}


@app.get("/health")
async def health():
    return {"status": "ok"}


@app.get("/v1/models")
async def list_models(_: str = Depends(require_agent)):
    now = int(time.time())
    return {
        "object": "list",
        "data": [
            {"id": m, "object": "model", "created": now, "owned_by": "builtin"}
            for m in BUILTIN_MODELS
        ],
    }


@app.post("/v1/chat/completions")
async def chat_completions(req: ChatCompletionRequest, _: str = Depends(require_agent)):
    created_ts = int(time.time())
    completion_id = f"chatcmpl-{uuid.uuid4().hex[:16]}"
    # Clamp to served models: anything unknown resolves to the default.
    model_name = req.model if req.model in BUILTIN_MODELS else resolve_model(req.model)

    active_tools = req.tools or []
    if req.functions:
        for f in req.functions:
            active_tools.append({"type": "function", "function": f})

    sys_prompt = ""
    if isinstance(req.system, str):
        sys_prompt = req.system
    elif isinstance(req.system, list):
        sys_prompt = "\n".join(b.get("text", "") for b in req.system if isinstance(b, dict))

    prompt_serialized = serialize_openai_messages(
        messages=req.messages,
        tools=active_tools if active_tools else None,
        system_prompt=sys_prompt if sys_prompt else None,
    )
    max_tok = req.max_completion_tokens or req.max_tokens

    def _usage(accumulated: str) -> Dict[str, int]:
        return {
            "prompt_tokens": max(1, len(prompt_serialized) // 4),
            "completion_tokens": max(1, len(accumulated) // 4),
            "total_tokens": max(2, (len(prompt_serialized) + len(accumulated)) // 4),
        }

    if req.stream:
        async def stream_openai_generator() -> AsyncIterator[str]:
            accumulated = ""
            try:
                first_chunk = {
                    "id": completion_id,
                    "object": "chat.completion.chunk",
                    "created": created_ts,
                    "model": model_name,
                    "choices": [{"index": 0, "delta": {"role": "assistant", "content": ""}, "finish_reason": None}],
                }
                yield f"data: {json.dumps(first_chunk)}\n\n"

                # Progressive streaming: forward narration live, but stop at
                # the first tool marker — partial XML can never be un-sent.
                sent_len = 0
                head_sent = ""
                async for chunk in tunnel.stream_tokens(
                    prompt=prompt_serialized,
                    model=model_name,
                    temperature=req.temperature,
                    max_tokens=max_tok,
                ):
                    accumulated += chunk
                    marker = _first_tool_marker(accumulated)
                    safe_end = marker if marker != -1 else len(accumulated)
                    if safe_end > sent_len:
                        new_text = accumulated[sent_len:safe_end]
                        sent_len += len(new_text)
                        head_sent += new_text
                        yield _sse_text_chunk(completion_id, created_ts, model_name, new_text)

                if not accumulated:
                    logger.warning("Gateway stream produced no tokens — upstream may be waking or limited")
                    yield f"data: {json.dumps({
                        'id': completion_id,
                        'object': 'chat.completion.chunk',
                        'created': created_ts,
                        'model': model_name,
                        'choices': [{'index': 0, 'delta': {'content': '[Upstream busy — please retry.]'}, 'finish_reason': None}],
                    })}\n\n"
                    yield f"data: {json.dumps({
                        'id': completion_id,
                        'object': 'chat.completion.chunk',
                        'created': created_ts,
                        'model': model_name,
                        'choices': [{'index': 0, 'delta': {}, 'finish_reason': 'stop'}],
                        'usage': _usage(''),
                    })}\n\n"
                    yield "data: [DONE]\n\n"
                    return

                cleaned_text, tool_calls = extract_tool_calls_and_text(accumulated, available_tools=active_tools)
                if tool_calls:
                    tc_delta = [
                        {
                            "index": idx,
                            "id": tc.get("id", f"call_{uuid.uuid4().hex[:12]}"),
                            "type": "function",
                            "function": {"name": tc["function"]["name"], "arguments": tc["function"]["arguments"]},
                        }
                        for idx, tc in enumerate(tool_calls)
                    ]
                    yield f"data: {json.dumps({
                        'id': completion_id,
                        'object': 'chat.completion.chunk',
                        'created': created_ts,
                        'model': model_name,
                        'choices': [{'index': 0, 'delta': {'tool_calls': tc_delta}, 'finish_reason': None}],
                    })}\n\n"
                    finish = "tool_calls"
                else:
                    # Send only what was never streamed: the whole text when no
                    # marker dance happened, else just the tail after the head.
                    remainder = cleaned_text
                    if head_sent and remainder.startswith(head_sent):
                        remainder = remainder[len(head_sent):]
                    if remainder:
                        yield _sse_text_chunk(completion_id, created_ts, model_name, remainder)
                    finish = "stop"
                yield f"data: {json.dumps({
                    'id': completion_id,
                    'object': 'chat.completion.chunk',
                    'created': created_ts,
                    'model': model_name,
                    'choices': [{'index': 0, 'delta': {}, 'finish_reason': finish}],
                    'usage': _usage(accumulated),
                })}\n\n"
                yield "data: [DONE]\n\n"
            except Exception as e:
                logger.error(f"Gateway stream error: {e}")
                yield f"data: {json.dumps({
                    'id': completion_id,
                    'object': 'chat.completion.chunk',
                    'created': created_ts,
                    'model': model_name,
                    'choices': [{'index': 0, 'delta': {'content': f'\n\n[Error: {str(e)}]'}, 'finish_reason': 'stop'}],
                })}\n\n"
                yield "data: [DONE]\n\n"

        return StreamingResponse(
            stream_openai_generator(), media_type="text/event-stream", headers=SSE_HEADERS
        )

    try:
        raw_text = await tunnel.complete(
            prompt=prompt_serialized,
            model=model_name,
            temperature=req.temperature,
            max_tokens=max_tok,
        )
    except Exception as e:
        logger.error(f"Gateway completion error: {e}")
        return JSONResponse(status_code=502, content={"error": {"message": "Upstream busy — please retry.", "code": 502}})

    cleaned_text, tool_calls = extract_tool_calls_and_text(raw_text, available_tools=active_tools)
    asst_message: Dict[str, Any] = {"role": "assistant", "content": cleaned_text or None}
    if tool_calls:
        asst_message["tool_calls"] = tool_calls
    return {
        "id": completion_id,
        "object": "chat.completion",
        "created": created_ts,
        "model": model_name,
        "choices": [{"index": 0, "message": asst_message, "finish_reason": "tool_calls" if tool_calls else "stop"}],
        "usage": _usage(raw_text),
    }
