import asyncio

from app.browser import browsers


async def main() -> None:
    session = await browsers.get("smoke-thread", "/tmp")
    try:
        await session.navigate("http://127.0.0.1:18765/index.html")
        assert "Browser Smoke" in await session.page.title()
        data = await session.inspect()
        assert "Click me" in data["text"]
        await session.click("#click")
        assert "clicked" in (await session.inspect())["text"]
        await session.type_text("#name", "Playwright")
        data = await session.inspect()
        assert any(item.get("value") == "Playwright" for item in data["inputs"])
        await session.press("Enter", "#name")
        shot = await session.screenshot()
        assert shot.image_base64 and shot.width == 1280
        print("browser runtime smoke test passed")
    finally:
        await browsers.close("smoke-thread")


if __name__ == "__main__":
    asyncio.run(main())
