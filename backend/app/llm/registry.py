"""Resolve a thread's model to a configured provider, falling back to env defaults."""

from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.crypto import decrypt
from app.db.models import Provider
from app.gateway.config import BUILTIN_MODELS
from app.llm.client import LLMClient


@dataclass(slots=True)
class ResolvedModel:
    provider_id: str
    provider_name: str
    kind: str
    base_url: str
    api_key: str
    model: str
    headers: dict[str, str]

    def client(self) -> LLMClient:
        return LLMClient(
            base_url=self.base_url,
            api_key=self.api_key,
            kind=self.kind,
            extra_headers=self.headers,
        )


def _env_default(model: str | None = None) -> ResolvedModel:
    return ResolvedModel(
        provider_id="env",
        provider_name="Default",
        kind="openai",
        base_url=settings.DEFAULT_LLM_BASE_URL,
        api_key=settings.DEFAULT_LLM_API_KEY,
        model=model or settings.DEFAULT_LLM_MODEL,
        headers={},
    )


def _builtin(model: str | None = None) -> ResolvedModel:
    """Embedded gateway models — always available, no provider needed."""
    return ResolvedModel(
        provider_id="builtin",
        provider_name="Built-in",
        kind="openai",
        base_url=settings.GATEWAY_URL,
        api_key=settings.GATEWAY_SHARED_SECRET,
        model=model if model in BUILTIN_MODELS else BUILTIN_MODELS[0],
        headers={},
    )


async def resolve_model(
    db: AsyncSession, *, provider_id: str | None = None, model: str | None = None
) -> ResolvedModel:
    # Explicit builtin selection always routes to the embedded gateway.
    if provider_id == "builtin" or model in BUILTIN_MODELS:
        return _builtin(model)
    # Explicit env-default selection keeps the legacy env behavior.
    if provider_id == "env":
        return _env_default(model)
    provider: Provider | None = None
    if provider_id and provider_id != "env":
        provider = await db.get(Provider, provider_id)
    if provider is None and model:
        rows = (await db.execute(select(Provider).where(Provider.enabled.is_(True)))).scalars().all()
        provider = next((p for p in rows if model in (p.models or [])), None)
    if provider is None:
        rows = (await db.execute(select(Provider).where(Provider.enabled.is_(True)))).scalars().all()
        provider = rows[0] if rows else None
    if provider is None:
        # Nothing configured at all: fall back to the embedded gateway so the
        # agent works out of the box with zero setup.
        return _builtin(model)
    if model is None and not provider.default_model and not provider.models:
        return _builtin(None)

    return ResolvedModel(
        provider_id=provider.id,
        provider_name=provider.name,
        kind=provider.kind,
        base_url=provider.base_url,
        api_key=decrypt(provider.api_key_enc),
        model=model or provider.default_model or (provider.models[0] if provider.models else ""),
        headers=provider.headers or {},
    )
