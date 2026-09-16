"""Third-party service clients. Tokens are stored encrypted and loaded on demand.

Two honest connection styles (researched per provider, 2026):
- Token direct: paste a bot token / personal access token / user access token.
  The probe below hits the provider's real identity endpoint.
- OAuth2 app flow: register your own app at the provider, paste the client
  ID + secret here, authorize in the popup, and tokens (with refresh) are
  stored encrypted. The redirect URI shown in the UI must be whitelisted
  in your app settings.
"""

from __future__ import annotations

import base64
import hashlib
import json
import secrets
import time
from typing import Any
from urllib.parse import urlencode

import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.crypto import decrypt
from app.db.models import Connector


class ServiceClient:
    name = "service"
    base_url = ""
    auth_scheme: str | None = "Bearer"
    auth_header = "Authorization"
    extra_headers: dict[str, str] | None = None

    def __init__(self, token: str):
        self.token = token

    def _headers(self) -> dict[str, str]:
        headers = {
            "Accept": "application/json",
            "User-Agent": "BhatiAiAgent/2.0",
        }
        if self.auth_scheme:
            headers[self.auth_header] = f"{self.auth_scheme} {self.token}".strip()
        for key, value in (self.extra_headers or {}).items():
            headers[key] = value.format(token=self.token) if "{token}" in value else value
        return headers

    async def request(self, method: str, path: str, **kwargs) -> Any:
        url = path if path.startswith("http") else f"{self.base_url}{path}"
        async with httpx.AsyncClient(timeout=45, follow_redirects=True) as client:
            r = await client.request(method, url, headers=self._headers(), **kwargs)
            r.raise_for_status()
            if not r.content:
                return {}
            try:
                return r.json()
            except ValueError:
                return {"text": r.text}

    async def request_bytes(self, method: str, path: str, **kwargs) -> bytes:
        """Raw bytes download (e.g. artifact archives)."""
        url = path if path.startswith("http") else f"{self.base_url}{path}"
        async with httpx.AsyncClient(timeout=120, follow_redirects=True) as client:
            r = await client.request(method, url, headers=self._headers(), **kwargs)
            r.raise_for_status()
            return r.content

    async def whoami(self) -> dict[str, Any]:
        raise NotImplementedError


class GitHubClient(ServiceClient):
    name = "github"
    base_url = "https://api.github.com"
    auth_scheme = "token"

    async def whoami(self):
        me = await self.request("GET", "/user")
        return {"login": me.get("login"), "name": me.get("name"), "avatar": me.get("avatar_url")}

    async def list_repos(self, per_page: int = 50):
        repos = await self.request(
            "GET", "/user/repos", params={"per_page": per_page, "sort": "updated"}
        )
        return [
            {
                "full_name": r["full_name"],
                "private": r["private"],
                "clone_url": r["clone_url"],
                "default_branch": r.get("default_branch", "main"),
                "description": r.get("description") or "",
                "updated_at": r.get("updated_at"),
            }
            for r in repos
        ]

    async def create_repo(self, name: str, private: bool = True, description: str = ""):
        return await self.request(
            "POST", "/user/repos", json={"name": name, "private": private, "description": description}
        )

    async def create_pull_request(self, repo: str, title: str, head: str, base: str, body: str = ""):
        return await self.request(
            "POST", f"/repos/{repo}/pulls", json={"title": title, "head": head, "base": base, "body": body}
        )

    def push_url(self, clone_url: str) -> str:
        return clone_url.replace("https://", f"https://x-access-token:{self.token}@")


class VercelClient(ServiceClient):
    name = "vercel"
    base_url = "https://api.vercel.com"

    async def whoami(self):
        me = await self.request("GET", "/v2/user")
        user = me.get("user", me)
        return {"username": user.get("username"), "email": user.get("email")}

    async def list_projects(self):
        data = await self.request("GET", "/v9/projects", params={"limit": 50})
        return [{"id": p["id"], "name": p["name"], "framework": p.get("framework")} for p in data.get("projects", [])]

    async def list_deployments(self, project: str = ""):
        params = {"limit": 20}
        if project:
            params["projectId"] = project
        data = await self.request("GET", "/v6/deployments", params=params)
        return [
            {"uid": d["uid"], "url": d.get("url"), "state": d.get("state"), "created": d.get("created")}
            for d in data.get("deployments", [])
        ]


class RenderClient(ServiceClient):
    name = "render"
    base_url = "https://api.render.com/v1"

    async def whoami(self):
        owners = await self.request("GET", "/owners", params={"limit": 1})
        if isinstance(owners, list) and owners:
            owner = owners[0].get("owner", {})
            return {"name": owner.get("name"), "email": owner.get("email")}
        return {}

    async def list_services(self):
        data = await self.request("GET", "/services", params={"limit": 50})
        return [
            {"id": s["service"]["id"], "name": s["service"]["name"], "type": s["service"]["type"]}
            for s in data
            if isinstance(s, dict) and "service" in s
        ]

    async def deploy(self, service_id: str):
        return await self.request("POST", f"/services/{service_id}/deploys", json={})


class HuggingFaceClient(ServiceClient):
    name = "huggingface"
    base_url = "https://huggingface.co/api"

    async def whoami(self):
        me = await self.request("GET", "/whoami-v2")
        return {"name": me.get("name"), "type": me.get("type")}

    async def list_spaces(self):
        me = await self.whoami()
        data = await self.request("GET", "/spaces", params={"author": me.get("name"), "limit": 50})
        return [{"id": s["id"], "sdk": s.get("sdk"), "private": s.get("private")} for s in data]


class SimpleTokenClient(ServiceClient):
    """Config-driven client for token-based services (whoami-style probe)."""

    def __init__(
        self,
        token: str,
        *,
        base_url: str = "",
        auth_scheme: str | None = "Bearer",
        auth_header: str = "Authorization",
        extra_headers: dict[str, str] | None = None,
        method: str = "GET",
        path: str = "",
        payload: dict[str, Any] | None = None,
        summarize: Any = None,
    ):
        super().__init__(token)
        self.base_url = base_url
        self.auth_scheme = auth_scheme
        self.auth_header = auth_header
        self.extra_headers = extra_headers or {}
        self._method = method
        self._path = path
        self._payload = payload
        self._summarize = summarize

    async def whoami(self):
        kwargs: dict[str, Any] = {}
        if self._payload is not None:
            kwargs["json"] = {
                k: (v.format(token=self.token) if isinstance(v, str) and "{token}" in v else v)
                for k, v in self._payload.items()
            }
        data = await self.request(self._method, self._path, **kwargs)
        if self._summarize is not None:
            return self._summarize(data if isinstance(data, dict) else {})
        return data if isinstance(data, dict) else {"result": data}


class TwilioClient(ServiceClient):
    """Twilio uses HTTP Basic auth over account SID + auth token."""

    name = "twilio"

    def __init__(self, token: str, extra: dict[str, str] | None = None):
        import base64

        super().__init__(token)
        self._sid = (extra or {}).get("account_sid", "")
        creds = base64.b64encode(f"{self._sid}:{token}".encode()).decode()
        self._basic = f"Basic {creds}"

    def _headers(self) -> dict[str, str]:
        headers = super()._headers()
        headers["Authorization"] = self._basic
        return headers

    async def whoami(self):
        data = await self.request(
            "GET", f"https://api.twilio.com/2010-04-01/Accounts/{self._sid}.json"
        )
        return {"sid": data.get("sid"), "name": data.get("friendly_name"), "status": data.get("status")}


# ------------------------------------------------------- social clients ---


class TelegramClient(ServiceClient):
    """Telegram Bot API: the token rides in the URL path, not a header."""

    name = "telegram"

    def __init__(self, token: str):
        super().__init__(token)
        self.base_url = f"https://api.telegram.org/bot{token}"

    def _headers(self) -> dict[str, str]:
        return {"Accept": "application/json", "User-Agent": "BhatiAiAgent/2.0"}

    async def whoami(self):
        me = await self.request("GET", "/getMe")
        result = me.get("result", me) if isinstance(me, dict) else {}
        return {
            "id": result.get("id"),
            "username": result.get("username"),
            "name": result.get("first_name"),
        }

    async def send_message(self, chat_id: str, text: str):
        return await self.request("POST", "/sendMessage", json={"chat_id": chat_id, "text": text})


class DiscordClient(ServiceClient):
    """Discord Bot API (Bot token prefix)."""

    name = "discord"
    base_url = "https://discord.com/api/v10"
    auth_scheme = "Bot"

    async def whoami(self):
        me = await self.request("GET", "/users/@me")
        return {
            "id": me.get("id"),
            "username": me.get("username"),
            "name": me.get("global_name") or me.get("username"),
            "bot": me.get("bot", False),
        }

    async def create_message(self, channel_id: str, content: str):
        return await self.request(
            "POST", f"/channels/{channel_id}/messages", json={"content": content}
        )


class SlackClient(ServiceClient):
    """Slack Web API (bot xoxb- or user xoxp- token, Bearer)."""

    name = "slack"
    base_url = "https://slack.com/api"

    async def whoami(self):
        data = await self.request("POST", "/auth.test", json={})
        return {
            "user": data.get("user"),
            "team": data.get("team"),
            "user_id": data.get("user_id"),
            "bot": bool(data.get("bot_id")),
        }

    async def post_message(self, channel: str, text: str):
        return await self.request(
            "POST", "/chat.postMessage", json={"channel": channel, "text": text}
        )


class TwitterClient(ServiceClient):
    """X (Twitter) API v2 — pass a user access token (OAuth 2.0 flow below)."""

    name = "twitter"
    base_url = "https://api.twitter.com/2"

    async def whoami(self):
        data = await self.request("GET", "/users/me")
        user = data.get("data", data) if isinstance(data, dict) else {}
        return {"id": user.get("id"), "username": user.get("username"), "name": user.get("name")}

    async def create_tweet(self, text: str):
        return await self.request("POST", "/tweets", json={"text": text})


class FacebookClient(ServiceClient):
    """Meta Graph API — pass a user access token."""

    name = "facebook"
    base_url = "https://graph.facebook.com/v26.0"

    async def whoami(self):
        me = await self.request("GET", "/me?fields=id,name")
        return {"id": me.get("id"), "name": me.get("name")}

    async def list_pages(self):
        data = await self.request("GET", "/me/accounts?fields=id,name,tasks")
        pages = data.get("data", []) if isinstance(data, dict) else []
        return [
            {"id": p.get("id"), "name": p.get("name"), "tasks": p.get("tasks", [])}
            for p in pages
            if isinstance(p, dict)
        ]


class InstagramClient(ServiceClient):
    """Instagram Professional account via a Facebook user token.

    Verifies the Facebook identity, then resolves the linked IG business
    account best-effort (personal accounts have none — reported honestly).
    """

    name = "instagram"
    base_url = "https://graph.facebook.com/v26.0"

    async def whoami(self):
        me = await self.request("GET", "/me?fields=id,name")
        out: dict[str, Any] = {"id": me.get("id"), "name": me.get("name")}
        try:
            accounts = await self.request("GET", "/me/accounts?fields=id")
            pages = accounts.get("data", []) if isinstance(accounts, dict) else []
            for page in pages:
                if not isinstance(page, dict) or not page.get("id"):
                    continue
                detail = await self.request(
                    "GET", f"/{page['id']}?fields=instagram_business_account"
                )
                ig = (detail or {}).get("instagram_business_account") or {}
                if ig.get("id"):
                    profile = await self.request(
                        "GET", f"/{ig['id']}?fields=id,username,account_type"
                    )
                    out.update(
                        {
                            "ig_id": profile.get("id"),
                            "username": profile.get("username"),
                            "account_type": profile.get("account_type"),
                        }
                    )
                    break
            else:
                out["note"] = "no linked Instagram business account found"
        except Exception as exc:
            out["note"] = f"page lookup skipped: {exc}"
        return out


class WhatsAppClient(ServiceClient):
    """WhatsApp Cloud API — system-user token + phone number ID."""

    name = "whatsapp"
    base_url = "https://graph.facebook.com/v26.0"

    def __init__(self, token: str, extra: dict[str, str] | None = None):
        super().__init__(token)
        self._number_id = (extra or {}).get("phone_number_id", "")

    async def whoami(self):
        if not self._number_id:
            raise ValueError("phone_number_id is required")
        data = await self.request(
            "GET", f"/{self._number_id}?fields=id,display_phone_number,verified_name"
        )
        return {
            "phone_number_id": data.get("id"),
            "number": data.get("display_phone_number"),
            "name": data.get("verified_name"),
        }

    async def send_text(self, to: str, body: str):
        if not self._number_id:
            raise ValueError("phone_number_id is required")
        return await self.request(
            "POST",
            f"/{self._number_id}/messages",
            json={"messaging_product": "whatsapp", "to": to, "text": {"body": body}},
        )


class LinkedInClient(ServiceClient):
    """LinkedIn — pass a user access token (OAuth 2.0 flow below)."""

    name = "linkedin"
    base_url = "https://api.linkedin.com/v2"

    async def whoami(self):
        me = await self.request("GET", "/userinfo")
        return {
            "id": me.get("sub"),
            "name": me.get("name"),
            "email": me.get("email"),
        }


class YouTubeClient(ServiceClient):
    """YouTube Data API — pass a Google OAuth access token (short-lived)."""

    name = "youtube"
    base_url = "https://www.googleapis.com/youtube/v3"

    async def whoami(self):
        data = await self.request("GET", "/channels?part=snippet&mine=true")
        items = data.get("items", []) if isinstance(data, dict) else []
        first = items[0] if items else {}
        snippet = first.get("snippet", {}) if isinstance(first, dict) else {}
        return {
            "channel_id": first.get("id"),
            "title": snippet.get("title"),
            "handle": snippet.get("customUrl"),
        }


class TikTokClient(ServiceClient):
    """TikTok — pass a user access token (OAuth 2.0 flow below)."""

    name = "tiktok"
    base_url = "https://open.tiktokapis.com/v2"

    async def whoami(self):
        data = await self.request(
            "GET", "/user/info/?fields=open_id,display_name,username,avatar_url"
        )
        user = (data.get("data") or {}).get("user", {}) if isinstance(data, dict) else {}
        return {
            "open_id": user.get("open_id"),
            "username": user.get("username"),
            "name": user.get("display_name"),
        }


# ------------------------------------------------------- OAuth2 framework ---


_oauth_pending: dict[str, dict[str, Any]] = {}
OAUTH_STATE_TTL = 600


def _pkce_pair() -> tuple[str, str]:
    verifier = secrets.token_urlsafe(64)
    digest = hashlib.sha256(verifier.encode()).digest()
    challenge = base64.urlsafe_b64encode(digest).rstrip(b"=").decode()
    return verifier, challenge


def _prune_pending() -> None:
    now = time.time()
    for key in [k for k, v in _oauth_pending.items() if v.get("expires", 0) < now]:
        _oauth_pending.pop(key, None)


def build_authorize_url(
    service: str,
    *,
    client_id: str,
    client_secret: str,
    redirect_uri: str,
    scopes: list[str] | None = None,
) -> tuple[str, str]:
    """Authorize URL + one-time state id. Secrets stay server-side in _pending."""
    from app.core.errors import AppError

    meta = SERVICES.get(service) or {}
    spec = meta.get("oauth")
    if not spec:
        raise AppError(f"{service} does not support OAuth — use a token", code="no_oauth")
    redirect = redirect_uri.strip()
    # Parse properly: startswith("http://localhost") would also allow
    # "http://localhost.evil.com". Only exact localhost/loopback hosts pass.
    from urllib.parse import urlparse as _urlparse

    try:
        _parts = _urlparse(redirect)
    except ValueError:
        raise AppError("redirect_uri is not a valid URL", code="bad_oauth")
    _host = (_parts.hostname or "").lower()
    _ok_https = _parts.scheme == "https" and bool(_host)
    _ok_local = _parts.scheme == "http" and _host in ("localhost", "127.0.0.1", "::1")
    if not (_ok_https or _ok_local):
        raise AppError(
            "redirect_uri must be https (http only for localhost) — "
            "it must match your app settings exactly",
            code="bad_oauth",
        )
    if not client_id.strip() or not redirect:
        raise AppError("client_id and redirect_uri are required", code="bad_oauth")
    _prune_pending()
    state_id = secrets.token_urlsafe(24)
    client_param = spec.get("client_param", "client_id")
    params: dict[str, str] = {
        "response_type": "code",
        client_param: client_id.strip(),
        "redirect_uri": redirect,
        "scope": " ".join(scopes or spec.get("scopes", [])),
        "state": state_id,
    }
    verifier: str | None = None
    if spec.get("pkce"):
        verifier, challenge = _pkce_pair()
        params["code_challenge"] = challenge
        params["code_challenge_method"] = "S256"
    params.update(spec.get("extra_auth_params") or {})
    _oauth_pending[state_id] = {
        "service": service,
        "client_id": client_id.strip(),
        "client_secret": client_secret,
        "redirect_uri": redirect,
        "verifier": verifier,
        "expires": time.time() + OAUTH_STATE_TTL,
    }
    return f"{spec['authorize_url']}?{urlencode(params)}", state_id


def _take_pending(state_id: str, service: str) -> dict[str, Any]:
    from app.core.errors import AppError

    _prune_pending()
    pending = _oauth_pending.pop(state_id, None)
    if not pending or pending.get("service") != service:
        raise AppError("OAuth session expired or invalid — start over", code="bad_state")
    return pending


async def exchange_oauth_code(service: str, *, code: str, state_id: str) -> dict[str, Any]:
    """Swap an authorization code for tokens. Returns token response + vault."""
    from app.core.errors import AppError

    meta = SERVICES.get(service) or {}
    spec = meta.get("oauth") or {}
    pending = _take_pending(state_id, service)
    client_param = spec.get("client_param", "client_id")
    form: dict[str, str] = {
        "grant_type": "authorization_code",
        "code": code,
        "redirect_uri": pending["redirect_uri"],
        client_param: pending["client_id"],
    }
    if pending.get("verifier"):
        form["code_verifier"] = pending["verifier"]
    headers = {"Accept": "application/json", "User-Agent": "BhatiAiAgent/2.0"}
    if spec.get("token_auth", "body") == "basic":
        creds = base64.b64encode(
            f"{pending['client_id']}:{pending['client_secret']}".encode()
        ).decode()
        headers["Authorization"] = f"Basic {creds}"
    elif pending.get("client_secret"):
        form["client_secret"] = pending["client_secret"]
    try:
        async with httpx.AsyncClient(timeout=30, follow_redirects=True) as client:
            response = await client.post(spec["token_url"], data=form, headers=headers)
            response.raise_for_status()
            tokens = response.json()
    except Exception as exc:
        raise AppError(f"Token exchange failed: {exc}", code="oauth_failed") from exc
    if not isinstance(tokens, dict) or not tokens.get("access_token"):
        raise AppError(
            f"Token exchange failed: {str(tokens)[:200]}", code="oauth_failed"
        )
    vault = {
        "refresh_token": tokens.get("refresh_token", ""),
        "expires_at": time.time() + int(tokens.get("expires_in") or 3600),
        "client_id": pending["client_id"],
        "client_secret": pending["client_secret"],
        "token_url": spec["token_url"],
        "token_auth": spec.get("token_auth", "body"),
        "client_param": client_param,
    }
    return {"tokens": tokens, "vault": vault}


async def refresh_oauth_token(service: str, vault: dict[str, Any]) -> tuple[str, dict[str, Any]]:
    """Use a stored refresh token. Returns (new_access_token, new_vault)."""
    from app.core.errors import AppError

    if not vault.get("refresh_token"):
        raise AppError("No refresh token stored — reconnect", code="oauth_expired")
    form = {
        "grant_type": "refresh_token",
        "refresh_token": vault["refresh_token"],
        vault.get("client_param", "client_id"): vault.get("client_id", ""),
    }
    headers = {"Accept": "application/json", "User-Agent": "BhatiAiAgent/2.0"}
    if vault.get("token_auth", "body") == "basic":
        creds = base64.b64encode(
            f"{vault.get('client_id', '')}:{vault.get('client_secret', '')}".encode()
        ).decode()
        headers["Authorization"] = f"Basic {creds}"
    elif vault.get("client_secret"):
        form["client_secret"] = vault["client_secret"]
    try:
        async with httpx.AsyncClient(timeout=30, follow_redirects=True) as client:
            response = await client.post(vault["token_url"], data=form, headers=headers)
            response.raise_for_status()
            tokens = response.json()
    except Exception as exc:
        raise AppError(f"Token refresh failed: {exc}", code="oauth_expired") from exc
    if not isinstance(tokens, dict) or not tokens.get("access_token"):
        raise AppError("Token refresh rejected — reconnect", code="oauth_expired")
    new_vault = dict(vault)
    new_vault["refresh_token"] = tokens.get("refresh_token") or vault["refresh_token"]
    new_vault["expires_at"] = time.time() + int(tokens.get("expires_in") or 3600)
    return str(tokens["access_token"]), new_vault


def _count(key: str, sub: str = "data"):
    def summarize(data: dict[str, Any]) -> dict[str, Any]:
        items = data.get(sub, data) if isinstance(data.get(sub, data), list) else []
        sample = [m.get("id") for m in items[:5] if isinstance(m, dict) and m.get("id")]
        return {key: len(items), "sample": sample}
    return summarize


TOKEN_FIELD = [{"key": "token", "label": "API Token", "secret": True}]


def _simple(**kwargs: Any):
    """Build function adapter for SimpleTokenClient services."""
    def build(token: str, extra: dict[str, str] | None = None):
        return SimpleTokenClient(token, **kwargs)
    return build


SERVICES: dict[str, dict[str, Any]] = {
    "github": {
        "label": "GitHub",
        "kind": "general",
        "client": GitHubClient,
        "build": lambda token, extra: GitHubClient(token),
        "fields": TOKEN_FIELD,
        "help": "Personal access token with `repo` scope — or connect with OAuth below",
        "docs": "https://github.com/settings/tokens",
        "oauth": {
            "authorize_url": "https://github.com/login/oauth/authorize",
            "token_url": "https://github.com/login/oauth/access_token",
            "scopes": ["repo", "read:user"],
            "token_auth": "body",
            "docs": "https://github.com/settings/developers (OAuth Apps → New)",
        },
    },
    "vercel": {
        "label": "Vercel",
        "client": VercelClient,
        "build": lambda token, extra: VercelClient(token),
        "fields": TOKEN_FIELD,
        "help": "Account token from vercel.com/account/tokens",
        "docs": "https://vercel.com/account/tokens",
    },
    "render": {
        "label": "Render",
        "client": RenderClient,
        "build": lambda token, extra: RenderClient(token),
        "fields": TOKEN_FIELD,
        "help": "API key from Render dashboard → Account Settings",
        "docs": "https://dashboard.render.com/u/settings",
    },
    "huggingface": {
        "label": "Hugging Face",
        "client": HuggingFaceClient,
        "build": lambda token, extra: HuggingFaceClient(token),
        "fields": TOKEN_FIELD,
        "help": "User access token with write scope",
        "docs": "https://huggingface.co/settings/tokens",
    },
    "gitlab": {
        "label": "GitLab",
        "build": _simple(
            base_url="https://gitlab.com/api/v4", auth_header="PRIVATE-TOKEN", auth_scheme="",
            path="/user", summarize=lambda d: {"username": d.get("username"), "name": d.get("name")},
        ),
        "fields": TOKEN_FIELD,
        "help": "Personal access token with `api` scope",
        "docs": "https://gitlab.com/-/user_settings/personal_access_tokens",
    },
    "tavily": {
        "label": "Tavily",
        "build": _simple(
            base_url="https://api.tavily.com", auth_scheme=None, method="POST", path="/search",
            payload={"api_key": "{token}", "query": "test", "max_results": 1, "include_answer": False},
            summarize=lambda d: {"ok": True, "credits_used": d.get("credits_used")},
        ),
        "fields": TOKEN_FIELD,
        "help": "API key from app.tavily.com (tvly-…)",
        "docs": "https://app.tavily.com/home",
    },
    "brave": {
        "label": "Brave Search",
        "build": _simple(
            base_url="https://api.search.brave.com", auth_header="X-Subscription-Token", auth_scheme="",
            path="/res/v1/web/search?q=test&count=1",
            summarize=lambda d: {"ok": True, "results": len(((d.get("web") or {}).get("results")) or [])},
        ),
        "fields": TOKEN_FIELD,
        "help": "API key from brave.com/search/api (BSA…)",
        "docs": "https://brave.com/search/api",
    },
    "discord": {
        "label": "Discord",
        "kind": "social",
        "client": DiscordClient,
        "build": lambda token, extra: DiscordClient(token),
        "fields": TOKEN_FIELD,
        "help": "Bot token from the Developer Portal (Reset Token) — or connect a user account with OAuth below",
        "docs": "https://discord.com/developers/applications",
        "oauth": {
            "authorize_url": "https://discord.com/oauth2/authorize",
            "token_url": "https://discord.com/api/v10/oauth2/token",
            "scopes": ["identify", "email"],
            "token_auth": "basic",
            "docs": "https://discord.com/developers/applications (OAuth2 → Add Redirect)",
        },
    },
    "slack": {
        "label": "Slack",
        "kind": "social",
        "client": SlackClient,
        "build": lambda token, extra: SlackClient(token),
        "fields": TOKEN_FIELD,
        "help": "Bot token (xoxb-…) or user token (xoxp-…) — or connect with OAuth below",
        "docs": "https://api.slack.com/apps",
        "oauth": {
            "authorize_url": "https://slack.com/oauth/v2/authorize",
            "token_url": "https://slack.com/api/oauth.v2.access",
            "scopes": ["chat:write", "channels:read", "users:read"],
            "token_auth": "body",
            "docs": "https://api.slack.com/apps (OAuth & Permissions → Redirect URLs)",
        },
    },
    "notion": {
        "label": "Notion",
        "build": _simple(
            base_url="https://api.notion.com", extra_headers={"Notion-Version": "2022-06-28"},
            path="/v1/users",
            summarize=lambda d: {"bots": len(d.get("results", [])) if isinstance(d.get("results"), list) else 0},
        ),
        "fields": TOKEN_FIELD,
        "help": "Internal integration token (ntn_… / secret_…)",
        "docs": "https://www.notion.so/my-account/integrations",
    },
    "linear": {
        "label": "Linear",
        "build": _simple(
            base_url="https://api.linear.app", method="POST", path="/graphql",
            payload={"query": "{ viewer { id name email } }"},
            summarize=lambda d: ((d.get("data") or {}).get("viewer") or {}),
        ),
        "fields": TOKEN_FIELD,
        "help": "Personal API key from Linear settings",
        "docs": "https://linear.app/settings/api",
    },
    "stripe": {
        "label": "Stripe",
        "build": _simple(
            base_url="https://api.stripe.com", path="/v1/account",
            summarize=lambda d: {"id": d.get("id"), "email": d.get("email"), "country": d.get("country")},
        ),
        "fields": TOKEN_FIELD,
        "help": "Secret key (sk_live_… / sk_test_…)",
        "docs": "https://dashboard.stripe.com/apikeys",
    },
    "twilio": {
        "label": "Twilio",
        "build": lambda token, extra: TwilioClient(token, extra),
        "fields": [
            {"key": "account_sid", "label": "Account SID (AC…)", "secret": False},
            {"key": "token", "label": "Auth Token", "secret": True},
        ],
        "help": "Account SID plus auth token from the Twilio console",
        "docs": "https://console.twilio.com",
    },
    "telegram": {
        "label": "Telegram",
        "kind": "social",
        "client": TelegramClient,
        "build": lambda token, extra: TelegramClient(token),
        "fields": TOKEN_FIELD,
        "help": "Bot token from @BotFather — the agent can send messages to any chat the bot is in",
        "docs": "https://t.me/BotFather",
    },
    "twitter": {
        "label": "X (Twitter)",
        "kind": "social",
        "client": TwitterClient,
        "build": lambda token, extra: TwitterClient(token),
        "fields": TOKEN_FIELD,
        "help": "User Access Token (OAuth 2.0 below is easier — tokens rotate every 2h without offline.access)",
        "docs": "https://developer.x.com/en/portal/dashboard",
        "oauth": {
            "authorize_url": "https://x.com/i/oauth2/authorize",
            "token_url": "https://api.twitter.com/2/oauth2/token",
            "scopes": ["tweet.read", "users.read", "tweet.write", "offline.access"],
            "token_auth": "basic",
            "pkce": True,
            "docs": "https://developer.x.com/en/portal/dashboard (App → User authentication → Web App)",
        },
    },
    "facebook": {
        "label": "Facebook",
        "kind": "social",
        "client": FacebookClient,
        "build": lambda token, extra: FacebookClient(token),
        "fields": TOKEN_FIELD,
        "help": "User access token (Graph API Explorer works for testing) — or connect with OAuth below",
        "docs": "https://developers.facebook.com/tools/explorer",
        "oauth": {
            "authorize_url": "https://www.facebook.com/v26.0/dialog/oauth",
            "token_url": "https://graph.facebook.com/v26.0/oauth/access_token",
            "scopes": ["pages_show_list", "pages_read_engagement", "pages_manage_posts"],
            "token_auth": "body",
            "docs": "https://developers.facebook.com/apps (Facebook Login → Valid redirect URIs)",
        },
    },
    "instagram": {
        "label": "Instagram",
        "kind": "social",
        "client": InstagramClient,
        "build": lambda token, extra: InstagramClient(token),
        "fields": TOKEN_FIELD,
        "help": "Facebook user token for an account linked to an Instagram Business/Creator profile",
        "docs": "https://developers.facebook.com/docs/instagram-platform",
    },
    "whatsapp": {
        "label": "WhatsApp",
        "kind": "social",
        "client": WhatsAppClient,
        "build": lambda token, extra: WhatsAppClient(token, extra),
        "fields": [
            {"key": "phone_number_id", "label": "Phone Number ID", "secret": False},
            {"key": "token", "label": "System User Token", "secret": True},
        ],
        "help": "Meta app token plus the sender Phone Number ID (WhatsApp → API Setup)",
        "docs": "https://developers.facebook.com/apps (WhatsApp → API Setup)",
    },
    "linkedin": {
        "label": "LinkedIn",
        "kind": "social",
        "client": LinkedInClient,
        "build": lambda token, extra: LinkedInClient(token),
        "fields": TOKEN_FIELD,
        "help": "User access token — or connect with OAuth below",
        "docs": "https://developer.linkedin.com (My Apps → Auth)",
        "oauth": {
            "authorize_url": "https://www.linkedin.com/oauth/v2/authorization",
            "token_url": "https://www.linkedin.com/oauth/v2/accessToken",
            "scopes": ["openid", "profile", "email"],
            "token_auth": "body",
            "docs": "https://developer.linkedin.com (My Apps → Auth → Redirect URLs)",
        },
    },
    "youtube": {
        "label": "YouTube",
        "kind": "social",
        "client": YouTubeClient,
        "build": lambda token, extra: YouTubeClient(token),
        "fields": TOKEN_FIELD,
        "help": "Google OAuth access token (short-lived — OAuth below refreshes automatically)",
        "docs": "https://console.cloud.google.com/apis/credentials",
        "oauth": {
            "authorize_url": "https://accounts.google.com/o/oauth2/v2/auth",
            "token_url": "https://oauth2.googleapis.com/token",
            "scopes": ["https://www.googleapis.com/auth/youtube.readonly"],
            "token_auth": "body",
            "extra_auth_params": {"access_type": "offline", "prompt": "consent"},
            "docs": "https://console.cloud.google.com/apis/credentials (OAuth client → Web → URIs)",
        },
    },
    "tiktok": {
        "label": "TikTok",
        "kind": "social",
        "client": TikTokClient,
        "build": lambda token, extra: TikTokClient(token),
        "fields": TOKEN_FIELD,
        "help": "User access token — or connect with OAuth below (needs an approved TikTok app for posting)",
        "docs": "https://developers.tiktok.com (My Apps → Login Kit)",
        "oauth": {
            "authorize_url": "https://www.tiktok.com/v2/auth/authorize/",
            "token_url": "https://open.tiktokapis.com/v2/oauth/token/",
            "scopes": ["user.info.basic"],
            "token_auth": "body",
            "client_param": "client_key",
            "pkce": True,
            "docs": "https://developers.tiktok.com (My Apps → Login Kit → Redirect URIs)",
        },
    },
}


def available_services() -> list[dict[str, Any]]:
    return [
        {
            "service": key,
            "label": meta["label"],
            "kind": meta.get("kind", "general"),
            "help": meta["help"],
            "docs": meta["docs"],
            "fields": meta.get("fields", TOKEN_FIELD),
            "oauth": (
                {
                    "scopes": list((meta["oauth"] or {}).get("scopes", [])),
                    "docs": (meta["oauth"] or {}).get("docs", ""),
                }
                if meta.get("oauth")
                else None
            ),
        }
        for key, meta in SERVICES.items()
    ]


from app.core.config import settings  # noqa: E402


async def get_client(db: AsyncSession | None, service: str) -> ServiceClient | None:
    from app.core.crypto import decrypt as _decrypt
    from app.core.crypto import encrypt as _encrypt

    meta = SERVICES.get(service)
    if not meta:
        return None
    token = ""
    extra: dict[str, str] = {}
    if db is not None:
        try:
            row = (
                await db.execute(select(Connector).where(Connector.service == service))
            ).scalar_one_or_none()
            if row and row.enabled:
                token = _decrypt(row.token_enc)
                account = row.account or {}
                extra = dict(account.get("_config", {}))
                # OAuth: silently refresh an expired access token so connected
                # accounts keep working without the user re-authorizing.
                vault_raw = account.get("_vault", "")
                if vault_raw:
                    try:
                        vault = json.loads(_decrypt(vault_raw))
                        if (
                            vault.get("refresh_token")
                            and vault.get("expires_at", 0) - 60 < time.time()
                        ):
                            token, new_vault = await refresh_oauth_token(service, vault)
                            row.token_enc = _encrypt(token)
                            account["_vault"] = _encrypt(json.dumps(new_vault))
                            row.account = account
                            await db.commit()
                    except Exception:
                        pass  # keep the old token; the probe will report the error
        except Exception:
            pass
    if not token:
        env_field = f"{service.upper()}_TOKEN"
        token = getattr(settings, env_field, "")
    if not token:
        return None
    build = meta.get("build") or (lambda token, extra: meta["client"](token))
    try:
        return build(token, extra)
    except Exception:
        return None
