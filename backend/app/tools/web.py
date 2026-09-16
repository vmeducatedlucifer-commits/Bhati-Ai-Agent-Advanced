"""Web search and page fetch."""

from __future__ import annotations

import re
from urllib.parse import quote_plus, urlparse

import httpx

from app.core.config import settings
from app.core.utils import truncate
from app.tools.base import ToolContext, ToolResult, integer, obj, string
from app.tools.registry import registry

UA = (
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/122.0 Safari/537.36 BhatiAiAgent/2.0"
)


def _to_text(html: str) -> str:
    try:
        from selectolax.parser import HTMLParser

        tree = HTMLParser(html)
        for tag in tree.css("script, style, noscript, svg, nav, footer, header, aside, form"):
            tag.decompose()
        node = tree.css_first("article") or tree.css_first("main") or tree.body
        text = node.text(separator="\n") if node else tree.text(separator="\n")
    except Exception:
        text = re.sub(r"<script.*?</script>|<style.*?</style>", " ", html, flags=re.S | re.I)
        text = re.sub(r"<[^>]+>", " ", text)
    lines = [ln.strip() for ln in text.splitlines()]
    return "\n".join(ln for ln in lines if ln)


async def _search_duckduckgo(query: str, limit: int) -> list[dict[str, str]]:
    url = f"https://html.duckduckgo.com/html/?q={quote_plus(query)}"
    async with httpx.AsyncClient(timeout=30, follow_redirects=True, headers={"User-Agent": UA}) as client:
        r = await client.post(url)
        r.raise_for_status()
        html = r.text
    results: list[dict[str, str]] = []
    try:
        from selectolax.parser import HTMLParser

        for node in HTMLParser(html).css(".result")[: limit * 2]:
            link = node.css_first("a.result__a")
            snippet = node.css_first(".result__snippet")
            if not link:
                continue
            results.append({
                "title": link.text(strip=True),
                "url": link.attributes.get("href", ""),
                "snippet": snippet.text(strip=True) if snippet else "",
            })
            if len(results) >= limit:
                break
    except Exception:
        for match in re.finditer(r'class="result__a"[^>]*href="([^"]+)"[^>]*>(.*?)</a>', html, re.S)  :
            results.append({"url": match.group(1), "title": re.sub(r"<[^>]+>", "", match.group(2)), "snippet": ""})
            if len(results) >= limit:
                break
    return results


async def _search_tavily(query: str, limit: int) -> list[dict[str, str]]:
    async with httpx.AsyncClient(timeout=30) as client:
        r = await client.post(
            "https://api.tavily.com/search",
            json={"api_key": settings.TAVILY_API_KEY, "query": query, "max_results": limit},
        )
        r.raise_for_status()
        data = r.json()
    return [
        {"title": i.get("title", ""), "url": i.get("url", ""), "snippet": i.get("content", "")}
        for i in data.get("results", [])
    ]


async def _search_brave(query: str, limit: int) -> list[dict[str, str]]:
    async with httpx.AsyncClient(timeout=30) as client:
        r = await client.get(
            "https://api.search.brave.com/res/v1/web/search",
            params={"q": query, "count": limit},
            headers={"X-Subscription-Token": settings.BRAVE_API_KEY, "Accept": "application/json"},
        )
        r.raise_for_status()
        data = r.json()
    return [
        {"title": i.get("title", ""), "url": i.get("url", ""), "snippet": i.get("description", "")}
        for i in (data.get("web") or {}).get("results", [])
    ]


@registry.tool(
    "web_search",
    "Search the web and return ranked results with titles, URLs and snippets.",
    obj({"query": string("Search query"), "limit": integer("Number of results", default=6)}, ["query"]),
    group="web",
)
async def web_search(ctx: ToolContext, query: str, limit: int = 6):
    provider = settings.SEARCH_PROVIDER
    try:
        if provider == "tavily" and settings.TAVILY_API_KEY:
            results = await _search_tavily(query, limit)
        elif provider == "brave" and settings.BRAVE_API_KEY:
            results = await _search_brave(query, limit)
        else:
            results = await _search_duckduckgo(query, limit)
    except Exception as exc:
        return ToolResult.error(f"search failed: {exc}")

    if not results:
        return ToolResult(content=f"No results for `{query}`")
    lines = [f"{i + 1}. {r['title']}\n   {r['url']}\n   {r['snippet'][:240]}" for i, r in enumerate(results)]
    return ToolResult(
        content="\n".join(lines),
        display={"kind": "search", "query": query, "results": results},
    )


@registry.tool(
    "web_fetch",
    "Fetch a URL and return its readable text content (HTML is stripped to article text).",
    obj(
        {
            "url": string("Absolute URL to fetch"),
            "max_chars": integer("Character budget for the returned text", default=20000),
        },
        ["url"],
    ),
    group="web",
)
async def web_fetch(ctx: ToolContext, url: str, max_chars: int = 20000):
    from app.core.net import assert_public_url

    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https"):
        return ToolResult.error("only http(s) URLs are supported")
    try:
        assert_public_url(url)
    except Exception as exc:
        return ToolResult.error(str(exc))
    # Stream with a byte cap instead of downloading the whole body into RAM.
    # Manual redirect chain (max 5): each hop is validated BEFORE requesting so
    # a public URL cannot bounce into 169.254.x.x / localhost / LAN.
    from urllib.parse import urljoin as _urljoin

    max_bytes = 5_000_000
    try:
        current = url
        content_type = ""
        body = ""
        async with httpx.AsyncClient(timeout=45, follow_redirects=False, headers={"User-Agent": UA}) as client:
            for _ in range(6):
                async with client.stream("GET", current) as r:
                    if r.status_code in (301, 302, 303, 307, 308):
                        location = r.headers.get("location", "")
                        if not location:
                            return ToolResult.error("fetch failed: redirect without location")
                        nxt = _urljoin(current, location)
                        try:
                            assert_public_url(nxt)
                        except Exception as exc:
                            return ToolResult.error(str(exc))
                        current = nxt
                        continue
                    r.raise_for_status()
                    try:
                        assert_public_url(str(r.url))
                    except Exception as exc:
                        return ToolResult.error(str(exc))
                    content_type = r.headers.get("content-type", "")
                    chunks: list[bytes] = []
                    total = 0
                    async for chunk in r.aiter_bytes(65536):
                        total += len(chunk)
                        if total > max_bytes:
                            return ToolResult.error("page exceeds 5 MB download cap")
                        chunks.append(chunk)
                    try:
                        body = b"".join(chunks).decode("utf-8", errors="replace")
                    except ValueError:
                        body = ""
                    break
            else:
                return ToolResult.error("fetch failed: too many redirects")
    except Exception as exc:
        return ToolResult.error(f"fetch failed: {exc}")

    text = _to_text(body) if "html" in content_type else body
    return ToolResult(
        content=f"# {url}\n\n{truncate(text, max_chars)}",
        display={"kind": "web", "url": url, "text": truncate(text, 200_000), "content_type": content_type},
    )
