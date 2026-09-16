"""Embedded gateway: agent-only auth, minimal surface, builtin model wiring."""

from __future__ import annotations

import asyncio

import pytest
from fastapi.testclient import TestClient

from app.gateway import server as gw
from app.gateway.config import BUILTIN_MODELS, settings as gw_settings


@pytest.fixture()
def gw_client():
    with TestClient(gw.app) as client:
        yield client


def _plaindict(resp):
    assert resp.status_code == 200, resp.text
    return resp.json()


def test_gateway_models_lists_only_builtins(gw_client):
    body = _plaindict(gw_client.get("/v1/models", headers={"Authorization": "Bearer dev"}))
    assert body["object"] == "list"
    assert [m["id"] for m in body["data"]] == list(BUILTIN_MODELS)
    for m in body["data"]:
        assert set(m) <= {"id", "object", "created", "owned_by"}


def test_gateway_has_minimal_surface():
    paths = sorted({getattr(r, "path", "") for r in gw.app.routes})
    assert "/v1/chat/completions" in paths
    assert "/v1/models" in paths
    assert "/health" in paths
    for banned in ("/playground", "/v1/sessions", "/v1/pool", "/v1/messages",
                   "/docs", "/redoc", "/openapi.json", "/api/agent/workspace/tree"):
        assert banned not in paths, banned


def test_gateway_health_reveals_nothing(gw_client):
    assert gw_client.get("/health").json() == {"status": "ok"}


def test_gateway_auth_enforced_when_secret_set(gw_client, monkeypatch):
    monkeypatch.setattr(gw_settings, "shared_secret", "s3cr3t-test")
    denied = gw_client.get("/v1/models")
    assert denied.status_code == 403
    denied2 = gw_client.get("/v1/models", headers={"Authorization": "Bearer wrong"})
    assert denied2.status_code == 403
    ok = gw_client.get("/v1/models", headers={"Authorization": "Bearer s3cr3t-test"})
    assert ok.status_code == 200, ok.text
    # Non-Bearer smuggling attempt fails too.
    smuggle = gw_client.get("/v1/models", headers={"Authorization": "s3cr3t-test"})
    assert smuggle.status_code == 403


def test_gateway_rejects_chat_without_secret(gw_client, monkeypatch):
    monkeypatch.setattr(gw_settings, "shared_secret", "s3cr3t-test")
    resp = gw_client.post("/v1/chat/completions", json={
        "model": BUILTIN_MODELS[0],
        "messages": [{"role": "user", "content": "hi"}],
    })
    assert resp.status_code == 403


class _FakeScalars:
    def __init__(self, rows):
        self._rows = rows

    def all(self):
        return self._rows


class _FakeResult:
    def __init__(self, rows):
        self._rows = rows

    def scalars(self):
        return _FakeScalars(self._rows)


class _FakeDB:
    def __init__(self, providers=()):
        self._providers = list(providers)

    async def get(self, *args, **kwargs):
        return None

    async def execute(self, *args, **kwargs):
        return _FakeResult(self._providers)


def test_resolve_prefers_builtin_ids_and_empty_setup():
    from app.llm import registry

    builtin = asyncio.run(registry.resolve_model(_FakeDB(), provider_id="builtin"))
    assert builtin.provider_id == "builtin"
    assert builtin.base_url.endswith("/v1")

    pro = asyncio.run(registry.resolve_model(_FakeDB(), model="gemini-1.5-pro"))
    assert pro.provider_id == "builtin" and pro.model == "gemini-1.5-pro"

    # Nothing configured at all -> embedded gateway, not a dead env default.
    fallback = asyncio.run(registry.resolve_model(_FakeDB()))
    assert fallback.provider_id == "builtin" and fallback.model == BUILTIN_MODELS[0]

    # Explicit env selection keeps legacy env behavior.
    env = asyncio.run(registry.resolve_model(_FakeDB(), provider_id="env", model="gpt-4o-mini"))
    assert env.provider_id == "env" and env.model == "gpt-4o-mini"


def test_models_catalogue_starts_with_builtins():
    from app.main import app

    with TestClient(app) as client:
        resp = client.get("/api/v1/providers/models")
        assert resp.status_code == 200, resp.text
        catalogue = resp.json()
        first_two = [(c["provider_id"], c["model"]) for c in catalogue[:2]]
        assert first_two == [("builtin", m) for m in BUILTIN_MODELS]
        for entry in catalogue:
            assert set(entry) == {"provider_id", "provider", "kind", "model"}, entry
