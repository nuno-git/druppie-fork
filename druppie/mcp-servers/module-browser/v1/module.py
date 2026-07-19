"""Browser MCP Server - Business Logic Module.

Thin async wrapper over Playwright (Chromium). Drives a single shared browser
session: one Browser, one context, one page. All tools operate on that page.

V1 LIMITATION: single shared session — concurrent browser-using agents will
interfere (one's navigate() changes the page out from under another). For
multi-session support, add a session_id param keyed to per-session contexts.

Chromium runs with --no-sandbox --disable-dev-shm-usage so it works inside a
container as root without a large /dev/shm. Anti-bot detection (Cloudflare,
PerimeterX, ...) on sites like booking.com/airlines may still block it; basic
mitigation would require playwright-stealth + residential proxies (not in v1).
"""

import base64
import logging

from playwright.async_api import (
    Browser,
    BrowserContext,
    Error as PWError,
    Page,
    TimeoutError as PWTimeout,
    async_playwright,
)

logger = logging.getLogger("browser-mcp")

DEFAULT_TIMEOUT_MS = 15000
NAV_TIMEOUT_MS = 30000
VIEWPORT = {"width": 1280, "height": 720}
LOCALE = "en-US"
TIMEZONE = "Europe/Amsterdam"
# --no-sandbox: Chromium refuses root otherwise. --disable-dev-shm-usage:
# write tabs to /tmp instead of the tiny default /dev/shm (k8s default 64Mi).
LAUNCH_ARGS = ["--no-sandbox", "--disable-dev-shm-usage", "--disable-gpu"]

MAX_TEXT_CHARS = 20000


class BrowserModule:
    """Business logic module for headless browser automation via Playwright."""

    def __init__(self) -> None:
        self._pw = None
        self._browser: Browser | None = None
        self._context: BrowserContext | None = None
        self._page: Page | None = None

    async def _ensure(self) -> Page:
        """Lazily start Playwright + Chromium + a fresh context/page.

        The browser stays alive for the lifetime of the module (pod). The
        page/context are recreated after close() or on first use.
        """
        if self._page is not None:
            return self._page
        if self._pw is None:
            self._pw = await async_playwright().start()
        if self._browser is None:
            logger.info("Launching Chromium (args=%s)", LAUNCH_ARGS)
            self._browser = await self._pw.chromium.launch(args=LAUNCH_ARGS)
        self._context = await self._browser.new_context(
            viewport=VIEWPORT, locale=LOCALE, timezone_id=TIMEZONE
        )
        self._context.set_default_timeout(DEFAULT_TIMEOUT_MS)
        self._page = await self._context.new_page()
        logger.info("Browser session ready (viewport=%s, locale=%s)", VIEWPORT, LOCALE)
        return self._page

    async def close(self) -> dict:
        """Reset the session: close page+context. Browser stays alive for reuse."""
        if self._page is not None:
            try:
                await self._page.close()
            except Exception:
                pass
        if self._context is not None:
            try:
                await self._context.close()
            except Exception:
                pass
        self._page = None
        self._context = None
        return {"success": True, "message": "session closed; recreated on next call"}

    async def navigate(
        self, url: str, wait_until: str = "domcontentloaded", timeout_ms: int = NAV_TIMEOUT_MS
    ) -> dict:
        page = await self._ensure()
        try:
            resp = await page.goto(url, wait_until=wait_until, timeout=timeout_ms)
            return {
                "success": True,
                "url": page.url,
                "status": resp.status if resp else None,
                "title": await page.title(),
            }
        except (PWError, PWTimeout) as e:
            return {"success": False, "error": str(e), "url": url}

    async def click(self, selector: str, timeout_ms: int = DEFAULT_TIMEOUT_MS) -> dict:
        page = await self._ensure()
        try:
            await page.click(selector, timeout=timeout_ms)
            return {"success": True, "selector": selector}
        except (PWError, PWTimeout) as e:
            return {"success": False, "error": str(e), "selector": selector}

    async def type_text(
        self,
        selector: str,
        text: str,
        clear_first: bool = True,
        timeout_ms: int = DEFAULT_TIMEOUT_MS,
    ) -> dict:
        page = await self._ensure()
        try:
            if clear_first:
                await page.fill(selector, "", timeout=timeout_ms)
            await page.type(selector, text, timeout=timeout_ms)
            return {"success": True, "selector": selector, "typed": text}
        except (PWError, PWTimeout) as e:
            return {"success": False, "error": str(e), "selector": selector}

    async def select_option(
        self, selector: str, value: str, timeout_ms: int = DEFAULT_TIMEOUT_MS
    ) -> dict:
        page = await self._ensure()
        try:
            selected = await page.select_option(selector, value, timeout=timeout_ms)
            return {"success": True, "selector": selector, "selected": selected}
        except (PWError, PWTimeout) as e:
            return {"success": False, "error": str(e), "selector": selector}

    async def press_key(self, key: str) -> dict:
        page = await self._ensure()
        try:
            await page.keyboard.press(key)
            return {"success": True, "key": key}
        except (PWError, PWTimeout) as e:
            return {"success": False, "error": str(e), "key": key}

    async def get_text(
        self, selector: str = "body", timeout_ms: int = DEFAULT_TIMEOUT_MS
    ) -> dict:
        page = await self._ensure()
        try:
            text = await page.inner_text(selector, timeout=timeout_ms)
            return {"success": True, "selector": selector, "text": text[:MAX_TEXT_CHARS]}
        except (PWError, PWTimeout) as e:
            return {"success": False, "error": str(e), "selector": selector}

    async def get_html(self, selector: str = "body") -> dict:
        page = await self._ensure()
        try:
            html = await page.inner_html(selector)
            return {"success": True, "selector": selector, "html": html[:MAX_TEXT_CHARS]}
        except (PWError, PWTimeout) as e:
            return {"success": False, "error": str(e), "selector": selector}

    async def snapshot(self, interesting_only: bool = True) -> dict:
        page = await self._ensure()
        try:
            tree = await page.accessibility.snapshot(interesting_only=interesting_only)
            return {"success": True, "snapshot": tree}
        except (PWError, PWTimeout) as e:
            return {"success": False, "error": str(e)}

    async def screenshot(self, full_page: bool = False) -> dict:
        page = await self._ensure()
        try:
            png = await page.screenshot(full_page=full_page)
            b64 = base64.b64encode(png).decode("ascii")
            return {
                "success": True,
                "full_page": full_page,
                "image_base64": b64,
                "mime": "image/png",
            }
        except (PWError, PWTimeout) as e:
            return {"success": False, "error": str(e)}

    async def wait_for(
        self,
        selector: str,
        state: str = "visible",
        timeout_ms: int = DEFAULT_TIMEOUT_MS,
    ) -> dict:
        page = await self._ensure()
        try:
            await page.wait_for_selector(selector, state=state, timeout=timeout_ms)
            return {"success": True, "selector": selector, "state": state}
        except (PWError, PWTimeout) as e:
            return {"success": False, "error": str(e), "selector": selector}

    async def evaluate(self, script: str) -> dict:
        page = await self._ensure()
        try:
            result = await page.evaluate(script)
            return {"success": True, "result": result}
        except (PWError, PWTimeout) as e:
            return {"success": False, "error": str(e)}

    async def go_back(self) -> dict:
        page = await self._ensure()
        try:
            resp = await page.go_back()
            return {
                "success": True,
                "url": page.url,
                "status": resp.status if resp else None,
            }
        except (PWError, PWTimeout) as e:
            return {"success": False, "error": str(e)}

    async def get_url_title(self) -> dict:
        page = await self._ensure()
        try:
            return {"success": True, "url": page.url, "title": await page.title()}
        except (PWError, PWTimeout) as e:
            return {"success": False, "error": str(e)}
