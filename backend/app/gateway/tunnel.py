"""
Gemini Free Web Tunnel Client with Real Browser Emulation, TLS Impersonation,
and Intelligent Multi-Session Pool Auto-Rotation.
Zero API keys, zero cookies required.
Emulates authentic local desktop/mobile browser sessions to work reliably on both
local devices and cloud deployments (Render, VPS, Docker, Termux).
"""
from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
import hashlib
import json
import logging
import random
import re
import time
from typing import Any, AsyncIterator, Dict, List, Optional, Tuple
import urllib.parse
import uuid

import httpx

try:
    from curl_cffi.requests import AsyncSession as CurlAsyncSession
    CURL_CFFI_AVAILABLE = True
except ImportError:
    CurlAsyncSession = None  # type: ignore
    CURL_CFFI_AVAILABLE = False

from .config import settings

logger = logging.getLogger(__name__)

BROWSER_PROFILES = [
    {
        "name": "chrome_windows",
        "impersonate": "chrome124",
        "user_agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/133.0.0.0 Safari/537.36",
        "sec_ch_ua": '"Not(A:Brand";v="99", "Google Chrome";v="133", "Chromium";v="133"',
        "sec_ch_ua_mobile": "?0",
        "sec_ch_ua_platform": '"Windows"',
    },
    {
        "name": "chrome_mac",
        "impersonate": "chrome124",
        "user_agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/133.0.0.0 Safari/537.36",
        "sec_ch_ua": '"Not(A:Brand";v="99", "Google Chrome";v="133", "Chromium";v="133"',
        "sec_ch_ua_mobile": "?0",
        "sec_ch_ua_platform": '"macOS"',
    },
    {
        "name": "chrome_linux",
        "impersonate": "chrome124",
        "user_agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/133.0.0.0 Safari/537.36",
        "sec_ch_ua": '"Not(A:Brand";v="99", "Google Chrome";v="133", "Chromium";v="133"',
        "sec_ch_ua_mobile": "?0",
        "sec_ch_ua_platform": '"Linux"',
    },
    {
        "name": "chrome_android",
        "impersonate": "chrome124",
        "user_agent": "Mozilla/5.0 (Linux; Android 14; Pixel 8 Pro) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/133.0.0.0 Mobile Safari/537.36",
        "sec_ch_ua": '"Not(A:Brand";v="99", "Google Chrome";v="133", "Chromium";v="133"',
        "sec_ch_ua_mobile": "?1",
        "sec_ch_ua_platform": '"Android"',
    },
]

USER_AGENTS = [p["user_agent"] for p in BROWSER_PROFILES]
DEFAULT_STREAM_URL = "https://gemini.google.com/_/BardChatUi/data/assistant.lamda.BardFrontendService/StreamGenerate"


class RateLimitError(Exception):
    """Raised when an API key or Web Tunnel session hits rate limit or quota exhaustion."""
    pass


def resolve_model(model_name: Optional[str]) -> str:
    """Normalize user model string to standard Gemini model name."""
    if not model_name:
        return settings.default_model
    m = model_name.lower().strip()
    if m.startswith("gemini-"):
        return m
    if "flash-lite" in m:
        return "gemini-2.0-flash-lite"
    if "flash" in m:
        return "gemini-2.0-flash"
    if "pro" in m:
        return "gemini-1.5-pro"
    if "claude" in m or "sonnet" in m or "fable" in m:
        return "gemini-2.0-flash"
    if "gpt-4" in m or "gpt-3" in m or "o1" in m or "o3" in m:
        return "gemini-2.0-flash"
    return settings.default_model


def _reqid() -> int:
    return random.randint(100000, 999999)


def _session_id() -> str:
    return "bypass_session_" + uuid.uuid4().hex[:12]


def _sapisidhash(sapisid: str, origin: str = "https://gemini.google.com") -> str:
    ts = int(time.time())
    h_data = f"{ts} {sapisid} {origin}"
    sha1 = hashlib.sha1(h_data.encode("utf-8")).hexdigest()
    return f"SAPISIDHASH {ts}_{sha1}"


@dataclass
class BrowserWarmSession:
    id: str = field(default_factory=lambda: f"sess_{uuid.uuid4().hex[:10]}")
    profile: Dict[str, str] = field(default_factory=dict)
    bl: str = ""
    f_sid: str = ""
    at: str = ""
    cookies: Dict[str, str] = field(default_factory=dict)
    custom_cookie: Optional[str] = None
    sapisid: Optional[str] = None
    created_at: float = field(default_factory=time.time)
    last_used_at: float = field(default_factory=time.time)
    request_count: int = 0
    rate_limited_until: float = 0.0

    @property
    def is_expired(self) -> bool:
        return (time.time() - self.created_at) > settings.session_ttl

    @property
    def is_rate_limited(self) -> bool:
        return time.time() < self.rate_limited_until

    @property
    def is_exhausted(self) -> bool:
        return self.request_count >= settings.max_requests_per_session

    @property
    def is_available(self) -> bool:
        return not self.is_expired and not self.is_rate_limited and not self.is_exhausted


class ApiKeyPool:
    """
    Manages a pool of official Gemini API keys with automatic round-robin rotation,
    quota exhaustion tracking (429/403), and temporary cooldown.
    """
    def __init__(self) -> None:
        self._keys: List[str] = []
        self._cooldowns: Dict[str, float] = {}
        self._request_counts: Dict[str, int] = {}
        self._current_idx: int = 0
        self._lock = asyncio.Lock()
        self.reload_keys()

    def reload_keys(self) -> None:
        self._keys = settings.get_api_keys()

    async def get_key(self, explicit_key: Optional[str] = None) -> Optional[str]:
        if explicit_key and explicit_key.startswith("AIza"):
            return explicit_key

        async with self._lock:
            if not self._keys:
                self.reload_keys()
            if not self._keys:
                return None

            now = time.time()
            available = [k for k in self._keys if self._cooldowns.get(k, 0) <= now]
            if not available:
                earliest = min(self._keys, key=lambda k: self._cooldowns.get(k, 0))
                remaining = max(0, int(self._cooldowns.get(earliest, 0) - now))
                logger.warning(f"All Gemini API keys in pool are in cooldown. Earliest resets in {remaining}s")
                return None

            self._current_idx = (self._current_idx + 1) % len(available)
            chosen = available[self._current_idx]
            self._request_counts[chosen] = self._request_counts.get(chosen, 0) + 1
            return chosen

    async def mark_rate_limited(self, key: str, cooldown_seconds: Optional[int] = None) -> None:
        async with self._lock:
            cd = cooldown_seconds or settings.session_cooldown_seconds
            self._cooldowns[key] = time.time() + cd
            logger.warning(f"Gemini API key {key[:8]}... marked rate-limited/exhausted. Cooldown for {cd}s")

    async def get_status(self) -> Dict[str, Any]:
        async with self._lock:
            now = time.time()
            return {
                "total_keys": len(self._keys),
                "active_keys": len([k for k in self._keys if self._cooldowns.get(k, 0) <= now]),
                "cooldown_keys": len([k for k in self._keys if self._cooldowns.get(k, 0) > now]),
            }


api_key_pool = ApiKeyPool()


class BrowserSessionPool:
    """
    Manages a live pool of pre-warmed browser sessions with TLS fingerprinting,
    dynamic build labels, automatic rotation, quota/rate-limit recovery,
    and background warming.
    """
    def __init__(self) -> None:
        self._pool: List[BrowserWarmSession] = []
        self._current_index: int = 0
        self._lock = asyncio.Lock()
        self._total_requests: int = 0
        self._rotations_count: int = 0

    @property
    def _current_session(self) -> Optional[BrowserWarmSession]:
        """Backward compatibility property for single-session inspections."""
        for s in self._pool:
            if s.is_available:
                return s
        return None

    def _pick_profile(self) -> Dict[str, str]:
        return random.choice(BROWSER_PROFILES)

    async def _create_warm_session(self, custom_cookie: Optional[str] = None) -> BrowserWarmSession:
        profile = self._pick_profile()
        bl = settings.stream_bl or "boq_assistant-bard-web-server_20260907.07_p0"
        f_sid = ""
        at_token = settings.gemini_at or ""
        cookies: Dict[str, str] = {}
        cookie_to_use = custom_cookie or settings.gemini_cookie

        headers = {
            "User-Agent": profile["user_agent"],
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8",
            "Accept-Language": "en-US,en;q=0.9",
            "Sec-Ch-Ua": profile["sec_ch_ua"],
            "Sec-Ch-Ua-Mobile": profile["sec_ch_ua_mobile"],
            "Sec-Ch-Ua-Platform": profile["sec_ch_ua_platform"],
            "Sec-Fetch-Dest": "document",
            "Sec-Fetch-Mode": "navigate",
            "Sec-Fetch-Site": "none",
            "Sec-Fetch-User": "?1",
            "Upgrade-Insecure-Requests": "1",
        }

        if cookie_to_use:
            headers["Cookie"] = cookie_to_use

        proxy_url = settings.upstream_proxy or None

        try:
            if CURL_CFFI_AVAILABLE:
                impersonate = settings.browser_impersonate or profile.get("impersonate", "chrome124")
                async with CurlAsyncSession(impersonate=impersonate, proxy=proxy_url) as client:
                    resp = await client.get("https://gemini.google.com/app", headers=headers, timeout=15)
                    if resp.status_code == 200:
                        body = resp.text
                        cookies = dict(client.cookies)
                        m_bl = re.search(r'\"cfb2h\":\"([^\"]+)\"', body)
                        if m_bl:
                            bl = m_bl.group(1)
                        m_sid = re.search(r'\"FdrFJe\":\"([^\"]+)\"', body)
                        if m_sid:
                            f_sid = m_sid.group(1)
                        m_at = re.search(r'\"SNlM0e\":\"([^\"]+)\"', body)
                        if m_at:
                            at_token = m_at.group(1)
            else:
                async with httpx.AsyncClient(follow_redirects=True, timeout=15.0, proxy=proxy_url) as client:
                    resp = await client.get("https://gemini.google.com/app", headers=headers)
                    if resp.status_code == 200:
                        body = resp.text
                        cookies = dict(resp.cookies)
                        m_bl = re.search(r'\"cfb2h\":\"([^\"]+)\"', body)
                        if m_bl:
                            bl = m_bl.group(1)
                        m_sid = re.search(r'\"FdrFJe\":\"([^\"]+)\"', body)
                        if m_sid:
                            f_sid = m_sid.group(1)
                        m_at = re.search(r'\"SNlM0e\":\"([^\"]+)\"', body)
                        if m_at:
                            at_token = m_at.group(1)
        except Exception as e:
            logger.warning(f"Browser warm-up probe encountered error (using fallback defaults): {e}")

        warm = BrowserWarmSession(
            profile=profile,
            bl=bl,
            f_sid=f_sid,
            at=at_token,
            cookies=cookies,
            custom_cookie=cookie_to_use,
            created_at=time.time(),
            last_used_at=time.time(),
        )
        return warm

    def _cleanup_pool_locked(self) -> None:
        """Remove expired sessions from memory."""
        self._pool = [s for s in self._pool if not s.is_expired and not (s.is_exhausted and not s.is_rate_limited)]

    async def get_session(self, force_refresh: bool = False, force_new: bool = False, exclude_session_id: Optional[str] = None) -> BrowserWarmSession:
        """
        Acquire a healthy session from the pool.
        Rotates automatically across pool when ROTATE_SESSION is enabled.
        If current session is rate-limited or exhausted, automatically rotates to next available session or creates a fresh one.
        """
        need_new = force_refresh or force_new
        async with self._lock:
            self._cleanup_pool_locked()
            available = [s for s in self._pool if s.is_available and (not exclude_session_id or s.id != exclude_session_id)]

            if not need_new and available:
                if settings.rotate_session_every_request:
                    self._current_index = (self._current_index + 1) % len(available)
                    sess = available[self._current_index]
                    self._rotations_count += 1
                else:
                    sess = min(available, key=lambda s: (s.request_count, s.last_used_at))

                sess.last_used_at = time.time()
                self._total_requests += 1
                return sess

            # Create fresh warm session
            cookie_pool = settings.get_cookies()
            chosen_cookie = random.choice(cookie_pool) if cookie_pool else None
            new_sess = await self._create_warm_session(custom_cookie=chosen_cookie)

            max_cap = max(settings.session_pool_size * 2, 10)
            if len(self._pool) < max_cap:
                self._pool.append(new_sess)
            else:
                self._pool.sort(key=lambda s: s.last_used_at)
                self._pool[0] = new_sess

            new_sess.last_used_at = time.time()
            self._total_requests += 1
            self._rotations_count += 1
            return new_sess

    async def mark_rate_limited(self, session_id: str, cooldown_seconds: Optional[int] = None) -> None:
        """Mark a session as rate-limited / quota exhausted so it is quarantined and pool rotates."""
        async with self._lock:
            cd = cooldown_seconds or settings.session_cooldown_seconds
            for s in self._pool:
                if s.id == session_id:
                    s.rate_limited_until = time.time() + cd
                    logger.warning(f"Session {session_id} rate-limited. Quarantined in pool for {cd}s.")
                    break

    async def mark_exhausted(self, session_id: str) -> None:
        """Mark session as exhausted (e.g. max requests reached or repeated error) and retire."""
        async with self._lock:
            for s in self._pool:
                if s.id == session_id:
                    s.request_count = settings.max_requests_per_session + 1
                    logger.info(f"Session {session_id} retired from pool.")
                    break

    async def record_success(self, session_id: str) -> None:
        """Record successful request and increment request counter."""
        async with self._lock:
            for s in self._pool:
                if s.id == session_id:
                    s.request_count += 1
                    s.last_used_at = time.time()
                    if s.request_count >= settings.max_requests_per_session:
                        logger.info(f"Session {session_id} reached {s.request_count} requests, will rotate.")
                    break

    def invalidate(self, session_id: Optional[str] = None) -> None:
        """Invalidate single session or whole pool."""
        if session_id:
            self._pool = [s for s in self._pool if s.id != session_id]
        else:
            self._pool.clear()

    async def get_pool_status(self) -> Dict[str, Any]:
        async with self._lock:
            self._cleanup_pool_locked()
            now = time.time()
            active = [s for s in self._pool if s.is_available]
            cooling = [s for s in self._pool if s.is_rate_limited]
            return {
                "pool_size": len(self._pool),
                "healthy_sessions": len(active),
                "cooling_sessions": len(cooling),
                "target_pool_size": settings.session_pool_size,
                "rotate_every_request": settings.rotate_session_every_request,
                "total_requests": self._total_requests,
                "rotations_count": self._rotations_count,
            }


BrowserSessionManager = BrowserSessionPool
session_pool = BrowserSessionPool()
session_manager = session_pool


class GeminiTunnel:
    """
    Reverse-engineered Web Tunnel with real browser TLS fingerprinting,
    intelligent session pool rotation, and multi-credential failover.
    Operates with zero API keys or official keys seamlessly.
    """

    def __init__(self) -> None:
        self._client: Optional[httpx.AsyncClient] = None
        self._build_label = settings.stream_bl or "boq_assistant-bard-web-server_20260907.07_p0"

    @property
    def client(self) -> httpx.AsyncClient:
        if self._client is None or self._client.is_closed:
            proxy_url = settings.upstream_proxy or None
            self._client = httpx.AsyncClient(
                timeout=httpx.Timeout(settings.request_timeout, connect=15.0),
                follow_redirects=True,
                http2=False,
                proxy=proxy_url,
            )
        return self._client

    async def aclose(self) -> None:
        if self._client and not self._client.is_closed:
            await self._client.aclose()

    def _generate_reqid(self) -> int:
        return _reqid()

    def _generate_sapisid_auth(self, sapisid: Optional[str] = None) -> Tuple[str, str]:
        sid = sapisid or ""
        ts = int(time.time())
        if sid:
            h_data = f"{ts} {sid} https://gemini.google.com"
        else:
            h_data = f"{ts}  https://gemini.google.com"
        sha1 = hashlib.sha1(h_data.encode("utf-8")).hexdigest()
        return sid, f"SAPISIDHASH {ts}_{sha1}"

    def _build_payload(
        self,
        prompt: Optional[str],
        session_id: str = "",
        response_id: str = "",
        choice_id: str = "",
        thinking_mode: int = 0,
        at_token: str = "",
    ) -> str:
        """Builds exact 102-element nested ArrayList structure matching Google Web Tunnel format."""
        prompt_str = prompt or ""
        lst: List[Any] = [None] * 102
        lst[0] = [prompt_str, 0, None, None, None, None, 0]
        lst[1] = None
        lst[2] = [session_id or "", response_id or "", choice_id or "", None, None, []]
        lst[3] = None
        lst[4] = None
        lst[10] = thinking_mode
        lst[101] = [None, None, None, None, []]

        inner_json = json.dumps(lst, separators=(",", ":"))
        outer = [None, inner_json]
        outer_json = json.dumps(outer, separators=(",", ":"))
        at_param = urllib.parse.quote(at_token or settings.gemini_at or "")
        return f"f.req={urllib.parse.quote(outer_json)}&at={at_param}"

    def _build_headers(
        self,
        auth_header: str,
        custom_cookie: Optional[str] = None,
        profile: Optional[Dict[str, str]] = None,
    ) -> Dict[str, str]:
        prof = profile or BROWSER_PROFILES[0]
        headers = {
            "User-Agent": prof["user_agent"],
            "Content-Type": "application/x-www-form-urlencoded;charset=utf-8",
            "Origin": "https://gemini.google.com",
            "Referer": "https://gemini.google.com/app",
            "X-Same-Domain": "1",
            "Sec-Ch-Ua": prof.get("sec_ch_ua", '"Not(A:Brand";v="99", "Google Chrome";v="133", "Chromium";v="133"'),
            "Sec-Ch-Ua-Mobile": prof.get("sec_ch_ua_mobile", "?0"),
            "Sec-Ch-Ua-Platform": prof.get("sec_ch_ua_platform", '"Windows"'),
            "Sec-Fetch-Dest": "empty",
            "Sec-Fetch-Mode": "cors",
            "Sec-Fetch-Site": "same-origin",
            "Accept": "*/*",
            "Accept-Language": "en-US,en;q=0.9",
        }

        if auth_header and "SAPISIDHASH" in auth_header:
            headers["Authorization"] = auth_header

        cookie_str = custom_cookie or settings.gemini_cookie
        if cookie_str:
            headers["Cookie"] = cookie_str
        return headers

    def _parse_wrb_blocks(self, text: str) -> List[Any]:
        """Parse all wrb.fr blocks in raw text using balanced bracket extraction."""
        blocks = []
        idx = 0
        target = '[["wrb.fr"'
        while True:
            pos = text.find(target, idx)
            if pos == -1:
                break
            depth = 0
            in_string = False
            escape = False
            end_pos = -1
            for i in range(pos, len(text)):
                c = text[i]
                if escape:
                    escape = False
                    continue
                if c == "\\":
                    escape = True
                    continue
                if c == '"':
                    in_string = not in_string
                    continue
                if not in_string:
                    if c == "[":
                        depth += 1
                    elif c == "]":
                        depth -= 1
                        if depth == 0:
                            end_pos = i + 1
                            break
            if end_pos != -1:
                chunk_json = text[pos:end_pos]
                try:
                    data = json.loads(chunk_json)
                    blocks.append(data)
                except Exception:
                    pass
                idx = end_pos
            else:
                break
        return blocks

    @staticmethod
    def _is_html_response(text: str) -> bool:
        """Detect if raw response is an HTML page (Google login, consent, CAPTCHA, error page)."""
        if not text:
            return False
        stripped = text.lstrip()[:500].lower()
        return bool(
            stripped.startswith("<!doctype") or stripped.startswith("<html")
            or "<head>" in stripped or "<body" in stripped
        )

    def _extract_stream_text(self, raw: str) -> str:
        """Extract complete response from wrb.fr payload lines."""
        # If the raw response is HTML (Google login/consent/CAPTCHA page), reject immediately
        if self._is_html_response(raw):
            logger.warning("Web tunnel returned HTML instead of API data (login/consent/CAPTCHA page). Treating as error.")
            return ""

        full_text = ""
        blocks = self._parse_wrb_blocks(raw)
        for block in blocks:
            if isinstance(block, list) and len(block) > 0 and block[0][0] == "wrb.fr":
                inner_str = block[0][2]
                if inner_str:
                    try:
                        inner_obj = json.loads(inner_str)
                        if isinstance(inner_obj, list) and len(inner_obj) > 4 and inner_obj[4]:
                            cand = inner_obj[4][0]
                            if len(cand) > 1 and cand[1]:
                                text = cand[1][0]
                                if isinstance(text, str) and len(text) > len(full_text):
                                    full_text = text
                    except Exception:
                        pass

        # If extracted text looks like HTML, reject it
        if self._is_html_response(full_text):
            logger.warning("Extracted text is HTML content, rejecting as invalid tunnel response.")
            return ""

        return self._clean_response_text(full_text)

    def _clean_response_text(self, text: str) -> str:
        """Clean code fence tags and remove trailing googleusercontent artifacts."""
        if not text:
            return ""
        text = re.sub(r"```([a-zA-Z0-9_-]+)\?[^\n\r]*", r"```\1", text)
        text = re.sub(r"https?://googleusercontent\.com/[^\s\n\r]*", "", text)
        text = re.sub(r"\n{2,}[A-Za-z0-9_]{10,}\s*$", "", text)
        return text.strip()

    def _clean_stream_chunk(self, text: str) -> str:
        """Clean streaming chunks without breaking partial code fences."""
        if not text:
            return ""
        text = re.sub(r"```([a-zA-Z0-9_-]+)\?[^\n\r]*", r"```\1", text)
        text = re.sub(r"https?://googleusercontent\.com/[^\s\n\r]*", "", text)
        return text

    async def _official_gemini_complete(
        self,
        api_key: str,
        model: str,
        prompt: str,
        temperature: Optional[float] = None,
        max_tokens: Optional[int] = None,
        system: Optional[str] = None,
    ) -> str:
        """Official Gemini REST API call with automatic rate limit detection."""
        gemini_model = resolve_model(model)
        url = f"https://generativelanguage.googleapis.com/v1beta/models/{gemini_model}:generateContent?key={api_key}"
        payload: Dict[str, Any] = {
            "contents": [{"parts": [{"text": prompt}], "role": "user"}]
        }
        if system:
            payload["system_instruction"] = {"parts": [{"text": system}]}
        gen_config: Dict[str, Any] = {}
        if temperature is not None:
            gen_config["temperature"] = temperature
        if max_tokens:
            gen_config["maxOutputTokens"] = max_tokens
        if gen_config:
            payload["generationConfig"] = gen_config

        async with httpx.AsyncClient(timeout=settings.request_timeout) as client:
            resp = await client.post(url, json=payload)
            if resp.status_code == 429 or "RESOURCE_EXHAUSTED" in resp.text:
                await api_key_pool.mark_rate_limited(api_key)
                raise RateLimitError(f"Official Gemini API 429 Quota Exceeded on key {api_key[:8]}")
            if resp.status_code in (403, 401):
                await api_key_pool.mark_rate_limited(api_key)
                raise RateLimitError(f"Official Gemini API {resp.status_code} Auth/Quota error on key {api_key[:8]}")
            if resp.status_code != 200:
                raise RuntimeError(f"Official Gemini API Error {resp.status_code}: {resp.text[:200]}")
            data = resp.json()
            candidates = data.get("candidates", [])
            if candidates and "content" in candidates[0]:
                parts = candidates[0]["content"].get("parts", [])
                return "".join(p.get("text", "") for p in parts)
            raise RuntimeError(f"Empty official response: {resp.text[:200]}")

    async def _official_gemini_stream(
        self,
        api_key: str,
        model: str,
        prompt: str,
        temperature: Optional[float] = None,
        max_tokens: Optional[int] = None,
        system: Optional[str] = None,
    ) -> AsyncIterator[str]:
        """Official Gemini REST API streaming fallback with rate limit handling."""
        gemini_model = resolve_model(model)
        url = f"https://generativelanguage.googleapis.com/v1beta/models/{gemini_model}:streamGenerateContent?alt=sse&key={api_key}"
        payload: Dict[str, Any] = {
            "contents": [{"parts": [{"text": prompt}], "role": "user"}]
        }
        if system:
            payload["system_instruction"] = {"parts": [{"text": system}]}
        gen_config: Dict[str, Any] = {}
        if temperature is not None:
            gen_config["temperature"] = temperature
        if max_tokens:
            gen_config["maxOutputTokens"] = max_tokens
        if gen_config:
            payload["generationConfig"] = gen_config

        async with httpx.AsyncClient(timeout=settings.request_timeout) as client:
            async with client.stream("POST", url, json=payload) as response:
                if response.status_code == 429 or response.status_code in (403, 401):
                    await api_key_pool.mark_rate_limited(api_key)
                    body = await response.aread()
                    raise RateLimitError(f"Official Gemini Stream {response.status_code}: {body.decode(errors='replace')[:200]}")
                if response.status_code != 200:
                    body = await response.aread()
                    raise RuntimeError(f"Official Gemini Stream Error {response.status_code}: {body.decode(errors='replace')[:200]}")

                async for line in response.aiter_lines():
                    if line.startswith("data: "):
                        data_str = line[6:].strip()
                        if data_str:
                            try:
                                data = json.loads(data_str)
                                for cand in data.get("candidates", []):
                                    for p in cand.get("content", {}).get("parts", []):
                                        txt = p.get("text", "")
                                        if txt:
                                            yield txt
                            except Exception:
                                pass

    async def stream_tokens(
        self,
        prompt: Optional[str] = None,
        session_id: str = "",
        response_id: str = "",
        choice_id: str = "",
        thinking_mode: int = 0,
        model: Optional[str] = None,
        messages: Optional[List[Dict[str, Any]]] = None,
        temperature: Optional[float] = None,
        max_tokens: Optional[int] = None,
        api_key: Optional[str] = None,
        system: Optional[str] = None,
    ) -> AsyncIterator[str]:
        """
        Stream text tokens incrementally with automatic session pool rotation and fallback.
        """
        if not prompt and messages:
            parts = []
            if system:
                parts.append(f"System: {system}")
            for m in messages:
                parts.append(f"{m.get('role', 'user')}: {m.get('content', '')}")
            prompt_text = "\n".join(parts)
        elif system and prompt:
            prompt_text = f"System: {system}\n{prompt}"
        else:
            prompt_text = prompt or "hello"

        # 1. Try explicit client-provided API key
        if api_key and api_key.startswith("AIza"):
            try:
                async for token in self._official_gemini_stream(
                    api_key=api_key,
                    model=model or settings.default_model,
                    prompt=prompt_text,
                    temperature=temperature,
                    max_tokens=max_tokens,
                    system=system,
                ):
                    yield token
                return
            except Exception as e:
                logger.warning(f"Explicit key stream error ({e}), falling back to session pool...")

        # 2. Try configured API Key Pool
        keys = settings.get_api_keys()
        for _ in range(len(keys)):
            pool_key = await api_key_pool.get_key()
            if not pool_key:
                break
            try:
                async for token in self._official_gemini_stream(
                    api_key=pool_key,
                    model=model or settings.default_model,
                    prompt=prompt_text,
                    temperature=temperature,
                    max_tokens=max_tokens,
                    system=system,
                ):
                    yield token
                return
            except RateLimitError as e:
                logger.warning(f"Key stream rate limit ({e}), rotating to next key/session...")
                continue
            except Exception as e:
                logger.warning(f"Key stream error ({e}), trying next...")
                continue

        # 3. Web Tunnel Stream with Automatic Session Pool Rotation
        max_attempts = max(settings.max_retries, 3)
        excluded_id: Optional[str] = None

        for attempt in range(max_attempts):
            warm_session = await session_pool.get_session(
                force_new=(attempt > 0),
                exclude_session_id=excluded_id,
            )
            excluded_id = warm_session.id
            sid, auth_hdr = self._generate_sapisid_auth(warm_session.sapisid or settings.gemini_sapisid)
            payload = self._build_payload(
                prompt=prompt_text,
                session_id=session_id or "",
                response_id=response_id or "",
                choice_id=choice_id or "",
                thinking_mode=thinking_mode,
                at_token=warm_session.at,
            )
            headers = self._build_headers(auth_hdr, custom_cookie=warm_session.custom_cookie, profile=warm_session.profile)
            reqid = _reqid()
            bl = warm_session.bl or self._build_label
            url = f"{DEFAULT_STREAM_URL}?bl={bl}&_reqid={reqid}&rt=c"
            if warm_session.f_sid:
                url += f"&f.sid={warm_session.f_sid}"

            proxy_url = settings.upstream_proxy or None
            last_len = 0
            emitted_any = False
            accumulated = ""
            html_detected = False

            try:
                if CURL_CFFI_AVAILABLE:
                    impersonate = settings.browser_impersonate or warm_session.profile.get("impersonate", "chrome124")
                    async with CurlAsyncSession(impersonate=impersonate, cookies=warm_session.cookies, proxy=proxy_url) as cclient:
                        r = await cclient.post(url, headers=headers, data=payload, stream=True, timeout=settings.request_timeout)
                        if r.status_code in (429, 403, 401, 503):
                            logger.warning(f"Stream tunnel HTTP {r.status_code} for session {warm_session.id}. Quarantining and rotating session...")
                            await session_pool.mark_rate_limited(warm_session.id)
                            continue
                        elif r.status_code != 200:
                            await session_pool.mark_exhausted(warm_session.id)
                            continue

                        async for chunk in r.aiter_content():
                            if not chunk:
                                continue
                            text_chunk = chunk.decode("utf-8", errors="replace")
                            accumulated += text_chunk
                            # Detect HTML responses early (Google login/consent/CAPTCHA pages)
                            if not emitted_any and self._is_html_response(accumulated):
                                logger.warning(f"Stream tunnel returned HTML for session {warm_session.id}. Rotating...")
                                html_detected = True
                                break
                            blocks = self._parse_wrb_blocks(accumulated)
                            for block in blocks:
                                if isinstance(block, list) and len(block) > 0 and block[0][0] == "wrb.fr":
                                    inner_str = block[0][2]
                                    if inner_str:
                                        try:
                                            inner_obj = json.loads(inner_str)
                                            if isinstance(inner_obj, list) and len(inner_obj) > 4 and inner_obj[4]:
                                                cand = inner_obj[4][0]
                                                if len(cand) > 1 and cand[1]:
                                                    raw_text = cand[1][0]
                                                    if isinstance(raw_text, str):
                                                        clean_txt = self._clean_stream_chunk(raw_text)
                                                        if len(clean_txt) > last_len:
                                                            delta = clean_txt[last_len:]
                                                            last_len = len(clean_txt)
                                                            emitted_any = True
                                                            yield delta
                                        except Exception:
                                            pass
                else:
                    async with self.client.stream("POST", url, headers=headers, content=payload, cookies=warm_session.cookies) as response:
                        if response.status_code in (429, 403, 401, 503):
                            logger.warning(f"Stream tunnel HTTP {response.status_code} for session {warm_session.id}. Quarantining and rotating session...")
                            await session_pool.mark_rate_limited(warm_session.id)
                            continue
                        elif response.status_code != 200:
                            await session_pool.mark_exhausted(warm_session.id)
                            continue

                        async for chunk in response.aiter_text():
                            accumulated += chunk
                            # Detect HTML responses early (Google login/consent/CAPTCHA pages)
                            if not emitted_any and self._is_html_response(accumulated):
                                logger.warning(f"Stream tunnel returned HTML for session {warm_session.id}. Rotating...")
                                html_detected = True
                                break
                            blocks = self._parse_wrb_blocks(accumulated)
                            for block in blocks:
                                if isinstance(block, list) and len(block) > 0 and block[0][0] == "wrb.fr":
                                    inner_str = block[0][2]
                                    if inner_str:
                                        try:
                                            inner_obj = json.loads(inner_str)
                                            if isinstance(inner_obj, list) and len(inner_obj) > 4 and inner_obj[4]:
                                                cand = inner_obj[4][0]
                                                if len(cand) > 1 and cand[1]:
                                                    raw_text = cand[1][0]
                                                    if isinstance(raw_text, str):
                                                        clean_txt = self._clean_stream_chunk(raw_text)
                                                        if len(clean_txt) > last_len:
                                                            delta = clean_txt[last_len:]
                                                            last_len = len(clean_txt)
                                                            emitted_any = True
                                                            yield delta
                                        except Exception:
                                            pass

                if html_detected:
                    await session_pool.mark_rate_limited(warm_session.id, cooldown_seconds=60)
                    continue

                if emitted_any:
                    await session_pool.record_success(warm_session.id)
                    return
                else:
                    # Stream finished without emitting any valid tokens (session limit reached)
                    logger.warning(f"Session {warm_session.id} stream finished with 0 tokens. Rotating session...")
                    await session_pool.mark_rate_limited(warm_session.id, cooldown_seconds=30)
                    continue

            except Exception as e:
                if not emitted_any:
                    logger.warning(f"Stream error before first token on session {warm_session.id}: {e}. Rotating to next session...")
                    await session_pool.mark_rate_limited(warm_session.id, cooldown_seconds=30)
                    continue
                else:
                    # If already emitted partial tokens, finish gracefully
                    return

        logger.error(f"Web Tunnel Stream exhausted after {max_attempts} pool rotations.")

    async def complete(
        self,
        prompt: Optional[str] = None,
        session_id: str = "",
        response_id: str = "",
        choice_id: str = "",
        thinking_mode: int = 0,
        model: Optional[str] = None,
        messages: Optional[List[Dict[str, Any]]] = None,
        temperature: Optional[float] = None,
        max_tokens: Optional[int] = None,
        api_key: Optional[str] = None,
        system: Optional[str] = None,
        **kwargs: Any,
    ) -> str:
        """
        Execute full completion request with automatic session pool rotation and rate-limit recovery.
        """
        if not prompt and messages:
            parts = []
            if system:
                parts.append(f"System: {system}")
            for m in messages:
                parts.append(f"{m.get('role', 'user')}: {m.get('content', '')}")
            prompt_text = "\n".join(parts)
        elif system and prompt:
            prompt_text = f"System: {system}\n{prompt}"
        else:
            prompt_text = prompt or "hello"

        # 1. Check for explicit client API key
        if api_key and api_key.startswith("AIza"):
            try:
                return await self._official_gemini_complete(
                    api_key=api_key,
                    model=model or settings.default_model,
                    prompt=prompt_text,
                    temperature=temperature,
                    max_tokens=max_tokens,
                    system=system,
                )
            except RateLimitError:
                logger.warning("Explicit API key rate limited, falling back to session pool.")
            except Exception as e:
                logger.warning(f"Explicit API key failed ({e}), falling back to session pool.")

        # 2. Try configured API Key Pool
        keys = settings.get_api_keys()
        for _ in range(len(keys)):
            pool_key = await api_key_pool.get_key()
            if not pool_key:
                break
            try:
                return await self._official_gemini_complete(
                    api_key=pool_key,
                    model=model or settings.default_model,
                    prompt=prompt_text,
                    temperature=temperature,
                    max_tokens=max_tokens,
                    system=system,
                )
            except RateLimitError as e:
                logger.warning(f"Key in pool rate limited ({e}), rotating to next key...")
                continue
            except Exception as e:
                logger.warning(f"Key failed ({e}), rotating to next key...")
                continue

        # 3. Web Tunnel Execution with Session Pool Rotation & Auto-Recovery
        max_attempts = max(settings.max_retries, 3)
        last_err: Optional[Exception] = None
        excluded_id: Optional[str] = None

        for attempt in range(max_attempts):
            warm_session = await session_pool.get_session(
                force_new=(attempt > 0),
                exclude_session_id=excluded_id,
            )
            excluded_id = warm_session.id
            sid, auth_hdr = self._generate_sapisid_auth(warm_session.sapisid or settings.gemini_sapisid)
            payload = self._build_payload(
                prompt=prompt_text,
                session_id=session_id or "",
                response_id=response_id or "",
                choice_id=choice_id or "",
                thinking_mode=thinking_mode,
                at_token=warm_session.at,
            )
            headers = self._build_headers(auth_hdr, custom_cookie=warm_session.custom_cookie, profile=warm_session.profile)
            reqid = _reqid()
            bl = warm_session.bl or self._build_label
            url = f"{DEFAULT_STREAM_URL}?bl={bl}&_reqid={reqid}&rt=c"
            if warm_session.f_sid:
                url += f"&f.sid={warm_session.f_sid}"

            proxy_url = settings.upstream_proxy or None

            try:
                if CURL_CFFI_AVAILABLE:
                    impersonate = settings.browser_impersonate or warm_session.profile.get("impersonate", "chrome124")
                    async with CurlAsyncSession(impersonate=impersonate, cookies=warm_session.cookies, proxy=proxy_url) as cclient:
                        resp = await cclient.post(url, headers=headers, data=payload, timeout=settings.request_timeout)
                        if resp.status_code in (429, 403, 401, 503):
                            logger.warning(f"Web Tunnel HTTP {resp.status_code} for session {warm_session.id}. Quarantining and rotating session...")
                            await session_pool.mark_rate_limited(warm_session.id)
                            last_err = RuntimeError(f"Web Tunnel HTTP {resp.status_code}: {resp.text[:200]}")
                            continue
                        elif resp.status_code != 200:
                            await session_pool.mark_exhausted(warm_session.id)
                            last_err = RuntimeError(f"Web Tunnel HTTP {resp.status_code}: {resp.text[:200]}")
                            continue
                        raw_resp = resp.text
                else:
                    resp = await self.client.post(url, headers=headers, content=payload, cookies=warm_session.cookies)
                    if resp.status_code in (429, 403, 401, 503):
                        logger.warning(f"Web Tunnel HTTP {resp.status_code} for session {warm_session.id}. Quarantining and rotating session...")
                        await session_pool.mark_rate_limited(warm_session.id)
                        last_err = RuntimeError(f"Web Tunnel HTTP {resp.status_code}: {resp.text[:200]}")
                        continue
                    elif resp.status_code != 200:
                        await session_pool.mark_exhausted(warm_session.id)
                        last_err = RuntimeError(f"Web Tunnel HTTP {resp.status_code}: {resp.text[:200]}")
                        continue
                    raw_resp = resp.text

                # Check if response body is HTML (Google login/consent/CAPTCHA page)
                if self._is_html_response(raw_resp):
                    logger.warning(f"Session {warm_session.id} returned HTML page (login/consent/CAPTCHA). Rotating session...")
                    await session_pool.mark_rate_limited(warm_session.id, cooldown_seconds=60)
                    last_err = RuntimeError("Web tunnel returned HTML page instead of API data")
                    continue

                # Check if response body indicates quota exhaustion or rate limits
                if "RESOURCE_EXHAUSTED" in raw_resp or "quota exceeded" in raw_resp.lower() or "limit reached" in raw_resp.lower():
                    logger.warning(f"Session {warm_session.id} response contained rate-limit indicator. Quarantining and rotating session...")
                    await session_pool.mark_rate_limited(warm_session.id)
                    last_err = RuntimeError("Session quota or rate limit exceeded")
                    continue

                text = self._extract_stream_text(raw_resp)
                if text:
                    await session_pool.record_success(warm_session.id)
                    return text

                # If text is empty, session may be throttled/invalid, quarantine and rotate
                logger.warning(f"Session {warm_session.id} returned empty candidate text. Rotating session...")
                await session_pool.mark_rate_limited(warm_session.id, cooldown_seconds=30)
                last_err = RuntimeError(f"Empty response extracted. Raw snippet: {raw_resp[:150]}")
                continue

            except Exception as e:
                logger.warning(f"Error on session {warm_session.id}: {e}. Rotating to next session...")
                await session_pool.mark_rate_limited(warm_session.id, cooldown_seconds=30)
                last_err = e
                continue

        raise RuntimeError(f"Failed to obtain response after {max_attempts} session pool rotations. Last error: {last_err}")
