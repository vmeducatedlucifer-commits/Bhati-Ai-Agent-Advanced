"""Agent-facing Playwright computer-use tools."""

from __future__ import annotations

from app.browser import BrowserUnavailable, browsers
from app.tools.base import ToolContext, ToolResult, boolean, integer, obj, string
from app.tools.registry import registry


def _session_error(exc: Exception) -> ToolResult:
    if isinstance(exc, BrowserUnavailable):
        return ToolResult.error(str(exc))
    return ToolResult.error(f"browser action failed: {exc}")


@registry.tool(
    "browser_navigate",
    "Open an HTTP(S) URL in the isolated Chromium browser and return its title and status.",
    obj({"url": string("HTTP(S) URL to open")}, ["url"]),
    group="browser",
)
async def browser_navigate(ctx: ToolContext, url: str):
    try:
        session = await browsers.get(ctx.thread_id, ctx.workspace)
        result = await session.navigate(url)
        await ctx.emit("browser_navigate", {"url": result["url"], "title": result["title"], "status_code": result["status_code"]})
        return ToolResult(content=f"Opened {result['url']} — {result['title']}", display={"kind": "browser", **result})
    except Exception as exc:
        return _session_error(exc)


@registry.tool(
    "browser_screenshot",
    "Capture the current Chromium viewport or full page as a PNG screenshot.",
    obj({"full_page": boolean("Capture the full scrollable page", default=False)}, []),
    group="browser",
)
async def browser_screenshot(ctx: ToolContext, full_page: bool = False):
    try:
        session = await browsers.get(ctx.thread_id, ctx.workspace)
        snapshot = await session.screenshot(full_page=full_page)
        return ToolResult(
            content=f"Screenshot captured for {snapshot.url} ({snapshot.width}x{snapshot.height}).",
            display={
                "kind": "browser",
                "action": "screenshot",
                "url": snapshot.url,
                "title": snapshot.title,
                "image_base64": snapshot.image_base64,
                "width": snapshot.width,
                "height": snapshot.height,
                "captured_at": snapshot.captured_at,
            },
        )
    except Exception as exc:
        return _session_error(exc)


@registry.tool(
    "browser_inspect",
    "Inspect the current page DOM for readable text, links, and form controls.",
    obj({"max_chars": integer("Maximum readable text characters", default=12000)}, []),
    group="browser",
)
async def browser_inspect(ctx: ToolContext, max_chars: int = 12000):
    try:
        session = await browsers.get(ctx.thread_id, ctx.workspace)
        data = await session.inspect(max_chars=max(500, min(max_chars, 50_000)))
        return ToolResult(content=str(data), display={"kind": "browser", "action": "inspect", **data})
    except Exception as exc:
        return _session_error(exc)


@registry.tool(
    "browser_click",
    "Click an element in Chromium using a CSS selector.",
    obj(
        {
            "selector": string("CSS selector for the element to click"),
            "button": string("Mouse button", enum=["left", "right", "middle"], default="left"),
            "click_count": integer("Number of clicks", default=1),
        },
        ["selector"],
    ),
    permission="write",
    mutating=True,
    group="browser",
)
async def browser_click(ctx: ToolContext, selector: str, button: str = "left", click_count: int = 1):
    try:
        session = await browsers.get(ctx.thread_id, ctx.workspace)
        result = await session.click(selector, button=button, click_count=max(1, min(click_count, 3)))
        await ctx.emit("browser_action", {"action": "click", **result})
        return ToolResult(content=f"Clicked `{selector}`.", display={"kind": "browser", "action": "click", **result})
    except Exception as exc:
        return _session_error(exc)


@registry.tool(
    "browser_type",
    "Type text into an element in Chromium using a CSS selector.",
    obj(
        {
            "selector": string("CSS selector for the input or editable element"),
            "text": string("Text to enter"),
            "clear": boolean("Replace existing value before typing", default=True),
        },
        ["selector", "text"],
    ),
    permission="write",
    mutating=True,
    group="browser",
)
async def browser_type(ctx: ToolContext, selector: str, text: str, clear: bool = True):
    try:
        session = await browsers.get(ctx.thread_id, ctx.workspace)
        result = await session.type_text(selector, text, clear=clear)
        await ctx.emit("browser_action", {"action": "type", "selector": selector, "characters": len(text), "url": result["url"]})
        return ToolResult(content=f"Typed {len(text)} characters into `{selector}`.", display={"kind": "browser", "action": "type", **result})
    except Exception as exc:
        return _session_error(exc)


@registry.tool(
    "browser_press",
    "Press a keyboard key or shortcut in Chromium, optionally targeting a selector.",
    obj({"key": string("Key or shortcut such as Enter or Control+L"), "selector": string("Optional CSS selector", default="")}, ["key"]),
    permission="write",
    mutating=True,
    group="browser",
)
async def browser_press(ctx: ToolContext, key: str, selector: str = ""):
    try:
        session = await browsers.get(ctx.thread_id, ctx.workspace)
        result = await session.press(key, selector or None)
        await ctx.emit("browser_action", {"action": "press", **result})
        return ToolResult(content=f"Pressed `{key}`.", display={"kind": "browser", "action": "press", **result})
    except Exception as exc:
        return _session_error(exc)


@registry.tool(
    "browser_mouse",
    "Move or click the Chromium mouse at viewport coordinates.",
    obj(
        {
            "action": string("Mouse action", enum=["move", "click", "dblclick"]),
            "x": integer("Viewport X coordinate"),
            "y": integer("Viewport Y coordinate"),
            "button": string("Mouse button", enum=["left", "right", "middle"], default="left"),
        },
        ["action", "x", "y"],
    ),
    permission="write",
    mutating=True,
    group="browser",
)
async def browser_mouse(ctx: ToolContext, action: str, x: int, y: int, button: str = "left"):
    try:
        session = await browsers.get(ctx.thread_id, ctx.workspace)
        result = await session.mouse(action, x, y, button=button)
        await ctx.emit("browser_action", result)
        return ToolResult(content=f"Mouse {action} at ({x}, {y}).", display={"kind": "browser", "action": "mouse", **result})
    except Exception as exc:
        return _session_error(exc)


@registry.tool(
    "browser_scroll",
    "Scroll the Chromium page by a horizontal and vertical pixel delta.",
    obj({"delta_x": integer("Horizontal scroll delta", default=0), "delta_y": integer("Vertical scroll delta", default=700)}, []),
    permission="write",
    mutating=True,
    group="browser",
)
async def browser_scroll(ctx: ToolContext, delta_x: int = 0, delta_y: int = 700):
    try:
        session = await browsers.get(ctx.thread_id, ctx.workspace)
        result = await session.scroll(delta_x=delta_x, delta_y=delta_y)
        await ctx.emit("browser_action", {"action": "scroll", **result})
        return ToolResult(content=f"Scrolled to ({result['scroll_x']}, {result['scroll_y']}).", display={"kind": "browser", "action": "scroll", **result})
    except Exception as exc:
        return _session_error(exc)
