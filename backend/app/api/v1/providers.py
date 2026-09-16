"""LLM providers and the model catalogue."""

from __future__ import annotations

from fastapi import APIRouter
from pydantic import BaseModel, Field
from sqlalchemy import select

from app.api.deps import DB, Auth
from app.core.config import settings
from app.core.crypto import decrypt, encrypt, mask
from app.core.errors import NotFound
from app.core.utils import iso
from app.db.models import Provider
from app.llm import LLMClient

router = APIRouter(prefix="/providers", tags=["providers"])

PRESETS = [
    {"name": "OpenAI", "kind": "openai", "base_url": "https://api.openai.com/v1", "default_model": "gpt-4o"},
    {"name": "Anthropic", "kind": "anthropic", "base_url": "https://api.anthropic.com/v1", "default_model": "claude-3-5-sonnet-latest"},
    {"name": "OpenRouter", "kind": "openai", "base_url": "https://openrouter.ai/api/v1", "default_model": "meta-llama/llama-3.3-70b-instruct"},
    {"name": "Groq", "kind": "openai", "base_url": "https://api.groq.com/openai/v1", "default_model": "llama-3.3-70b-versatile"},
    {"name": "Together", "kind": "openai", "base_url": "https://api.together.xyz/v1", "default_model": "meta-llama/Meta-Llama-3.1-70B-Instruct-Turbo"},
    {"name": "DeepSeek", "kind": "openai", "base_url": "https://api.deepseek.com/v1", "default_model": "deepseek-chat"},
    {"name": "Mistral", "kind": "openai", "base_url": "https://api.mistral.ai/v1", "default_model": "mistral-large-latest"},
    {"name": "Ollama (local)", "kind": "openai", "base_url": "http://localhost:11434/v1", "default_model": "llama3.2"},
    {"name": "LM Studio (local)", "kind": "openai", "base_url": "http://localhost:1234/v1", "default_model": "local-model"},
]


class ProviderIn(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    kind: str = Field(default="openai", pattern="^(openai|anthropic)$")
    base_url: str
    api_key: str = ""
    default_model: str = ""
    models: list[str] = Field(default_factory=list)
    headers: dict[str, str] = Field(default_factory=dict)


class ProviderPatch(BaseModel):
    name: str | None = None
    base_url: str | None = None
    api_key: str | None = None
    default_model: str | None = None
    models: list[str] | None = None
    headers: dict[str, str] | None = None
    enabled: bool | None = None


def serialize(provider: Provider) -> dict:
    return {
        "id": provider.id,
        "name": provider.name,
        "kind": provider.kind,
        "base_url": provider.base_url,
        "api_key_masked": mask(decrypt(provider.api_key_enc)),
        "has_key": bool(provider.api_key_enc),
        "models": provider.models or [],
        "default_model": provider.default_model,
        "enabled": provider.enabled,
        # Header values often carry secrets — expose names only.
        "headers": {k: "***" for k in (provider.headers or {})},
        "created_at": iso(provider.created_at),
    }


@router.get("/presets")
async def presets(_: Auth):
    return PRESETS


@router.get("")
async def list_providers(db: DB, _: Auth):
    rows = (await db.execute(select(Provider).order_by(Provider.created_at))).scalars().all()
    out = [serialize(p) for p in rows]
    if settings.DEFAULT_LLM_BASE_URL and settings.DEFAULT_LLM_MODEL:
        out.insert(0, {
            "id": "env",
            "name": "Default (from environment)",
            "kind": "openai",
            "base_url": settings.DEFAULT_LLM_BASE_URL,
            "api_key_masked": mask(settings.DEFAULT_LLM_API_KEY),
            "has_key": bool(settings.DEFAULT_LLM_API_KEY),
            "models": [settings.DEFAULT_LLM_MODEL],
            "default_model": settings.DEFAULT_LLM_MODEL,
            "enabled": True,
            "headers": {},
            "readonly": True,
        })
    return out


@router.post("", status_code=201)
async def create_provider(body: ProviderIn, db: DB, _: Auth):
    provider = Provider(
        name=body.name,
        kind=body.kind,
        base_url=body.base_url.rstrip("/"),
        api_key_enc=encrypt(body.api_key),
        default_model=body.default_model,
        models=body.models,
        headers=body.headers,
    )
    db.add(provider)
    await db.commit()
    return serialize(provider)


@router.patch("/{provider_id}")
async def patch_provider(provider_id: str, body: ProviderPatch, db: DB, _: Auth):
    provider = await db.get(Provider, provider_id)
    if not provider:
        raise NotFound("Provider not found")
    data = body.model_dump(exclude_none=True)
    if "api_key" in data:
        new_key = data.pop("api_key")
        # Frontend never receives the real key — empty/"***" means "keep old".
        if new_key not in ("", "***", "****", "********"):
            provider.api_key_enc = encrypt(new_key)
    if "headers" in data:
        incoming = data.pop("headers") or {}
        current = dict(provider.headers or {})
        for k, v in incoming.items():
            # "***" is the masked placeholder from serialize() — keep the secret.
            if v in ("***", "****", "********"):
                continue
            if v == "" or v is None:
                current.pop(k, None)
            else:
                current[k] = v
        provider.headers = current
    for field, value in data.items():
        setattr(provider, field, value)
    await db.commit()
    return serialize(provider)


@router.delete("/{provider_id}")
async def delete_provider(provider_id: str, db: DB, _: Auth):
    provider = await db.get(Provider, provider_id)
    if not provider:
        raise NotFound("Provider not found")
    await db.delete(provider)
    await db.commit()
    return {"deleted": provider_id}


@router.post("/{provider_id}/refresh-models")
async def refresh_models(provider_id: str, db: DB, _: Auth):
    provider = await db.get(Provider, provider_id)
    if not provider:
        raise NotFound("Provider not found")
    from app.core.net import assert_public_url

    # Explicit user-configured LLM endpoint: allow loopback (Ollama/LM Studio)
    # but still block LAN + cloud metadata.
    assert_public_url(provider.base_url, allow_loopback=True)
    client = LLMClient(
        base_url=provider.base_url,
        api_key=decrypt(provider.api_key_enc),
        kind=provider.kind,
        extra_headers=provider.headers or {},
    )
    try:
        models = await client.list_models()
    except Exception as exc:
        return {"ok": False, "error": str(exc), "models": provider.models or []}
    if models:
        provider.models = models
        if not provider.default_model:
            provider.default_model = models[0]
        await db.commit()
    return {"ok": True, "models": models}


@router.post("/test")
async def test_provider(body: ProviderIn, _: Auth):
    from app.core.net import assert_public_url

    assert_public_url(body.base_url, allow_loopback=True)
    client = LLMClient(
        base_url=body.base_url, api_key=body.api_key, kind=body.kind, extra_headers=body.headers
    )
    model = body.default_model or (body.models[0] if body.models else "")
    if not model:
        try:
            found = await client.list_models()
        except Exception as exc:
            return {"ok": False, "error": str(exc)}
        return {"ok": True, "models": found}
    try:
        completion = await client.complete(
            model=model,
            messages=[{"role": "user", "content": "Reply with the single word: ok"}],
            temperature=0,
            max_tokens=10,
        )
    except Exception as exc:
        return {"ok": False, "error": str(exc)}
    return {"ok": True, "reply": completion.content.strip()[:100], "model": model}


@router.get("/models")
async def all_models(db: DB, _: Auth):
    from app.gateway.config import BUILTIN_MODELS

    rows = (await db.execute(select(Provider).where(Provider.enabled.is_(True)))).scalars().all()
    catalogue = [
        # Built-in embedded-gateway models first: always available, even with
        # zero user providers. Only ids + generic provider label are exposed —
        # no URLs, keys, or backend details ever leave the backend.
        *[
            {"provider_id": "builtin", "provider": "Built-in", "kind": "openai", "model": m}
            for m in BUILTIN_MODELS
        ],
        *[
            {"provider_id": p.id, "provider": p.name, "kind": p.kind, "model": m}
            for p in rows
            for m in (p.models or ([p.default_model] if p.default_model else []))
        ],
    ]
    if settings.DEFAULT_LLM_MODEL:
        # Env default stays available but after the built-ins, so fresh
        # installs default to the embedded gateway models.
        catalogue.append({
            "provider_id": "env",
            "provider": "Default",
            "kind": "openai",
            "model": settings.DEFAULT_LLM_MODEL,
        })
    return catalogue
