"""Browser v1 — MCP Tool Definitions.

Single source of truth for tool contract:
- Tool name, description, input schema via @mcp.tool()
- Version and module_id via @mcp.tool(meta={...})
- Agent guidance via FastMCP(instructions=...)
"""

from fastmcp import FastMCP

from .module import BrowserModule

MODULE_ID = "browser"
MODULE_VERSION = "1.0.0"

mcp = FastMCP(
    "Browser v1",
    version=MODULE_VERSION,
    instructions=(
        "Drive a headless Chromium browser to navigate and interact with "
        "JavaScript-rendered pages (e.g. booking engines, SPAs, dashboards) "
        "that a plain HTTP fetch cannot read.\n\n"
        "TYPICAL FLOW:\n"
        "1. navigate(url) to open the page (JS executes).\n"
        "2. snapshot() to get the accessibility tree — your 'eyes' on the "
        "page; it lists interactive elements with role/name.\n"
        "3. click / type / select_option to drive the UI.\n"
        "4. wait_for(selector) when content loads after an action.\n"
        "5. get_text(selector) to read results, or evaluate(js) for precise "
        "DOM extraction (e.g. prices).\n\n"
        "Selectors use Playwright syntax: CSS ('#id', '.cls'), text "
        "('text=Book'), role-based, or XPath. Prefer snapshot() to discover "
        "what to click.\n\n"
        "LIMITATION: single shared browser session. Call close() when done."
    ),
)

module = BrowserModule()


@mcp.tool(
    name="navigate",
    description=(
        "Open a URL in the browser; the page's JavaScript executes. Returns "
        "the final URL (after redirects), HTTP status, and page title."
    ),
    meta={"module_id": MODULE_ID, "version": MODULE_VERSION},
)
async def navigate(url: str, wait_until: str = "domcontentloaded", timeout_ms: int = 30000) -> dict:
    return await module.navigate(url=url, wait_until=wait_until, timeout_ms=timeout_ms)


@mcp.tool(
    name="click",
    description=(
        "Click an element. `selector` is Playwright syntax (CSS like '#id', "
        "'.cls'; 'text=Book Now'; role=button[name='Search']). Auto-waits for "
        "the element to be clickable."
    ),
    meta={"module_id": MODULE_ID, "version": MODULE_VERSION},
)
async def click(selector: str, timeout_ms: int = 10000) -> dict:
    return await module.click(selector=selector, timeout_ms=timeout_ms)


@mcp.tool(
    name="type",
    description=(
        "Type text into a form field (cleared first by default). Use for "
        "search boxes, inputs, textareas."
    ),
    meta={"module_id": MODULE_ID, "version": MODULE_VERSION},
)
async def type_text(
    selector: str, text: str, clear_first: bool = True, timeout_ms: int = 10000
) -> dict:
    return await module.type_text(
        selector=selector, text=text, clear_first=clear_first, timeout_ms=timeout_ms
    )


@mcp.tool(
    name="select_option",
    description=(
        "Select an <option> in a <select> dropdown by its value attribute. "
        "Use for guests/room/currency selectors on booking forms."
    ),
    meta={"module_id": MODULE_ID, "version": MODULE_VERSION},
)
async def select_option(selector: str, value: str, timeout_ms: int = 10000) -> dict:
    return await module.select_option(selector=selector, value=value, timeout_ms=timeout_ms)


@mcp.tool(
    name="press_key",
    description=(
        "Press a keyboard key (e.g. 'Enter', 'Tab', 'Escape'). Use 'Enter' "
        "to submit a search form."
    ),
    meta={"module_id": MODULE_ID, "version": MODULE_VERSION},
)
async def press_key(key: str) -> dict:
    return await module.press_key(key=key)


@mcp.tool(
    name="get_text",
    description=(
        "Return the visible text content of an element (default: the whole "
        "page body). Use to read rendered results."
    ),
    meta={"module_id": MODULE_ID, "version": MODULE_VERSION},
)
async def get_text(selector: str = "body", timeout_ms: int = 10000) -> dict:
    return await module.get_text(selector=selector, timeout_ms=timeout_ms)


@mcp.tool(
    name="get_html",
    description=(
        "Return raw HTML of an element (default: body). Use only when you "
        "need exact markup; prefer get_text / snapshot."
    ),
    meta={"module_id": MODULE_ID, "version": MODULE_VERSION},
)
async def get_html(selector: str = "body") -> dict:
    return await module.get_html(selector=selector)


@mcp.tool(
    name="snapshot",
    description=(
        "Return the page's accessibility tree (role/name/value for "
        "interactive elements). The best way to 'see' what's on the page "
        "without drowning in HTML. Use after navigate to plan interactions."
    ),
    meta={"module_id": MODULE_ID, "version": MODULE_VERSION},
)
async def snapshot(interesting_only: bool = True) -> dict:
    return await module.snapshot(interesting_only=interesting_only)


@mcp.tool(
    name="screenshot",
    description=(
        "Capture a PNG screenshot returned as base64. For vision-capable "
        "models or debugging. Large output — prefer snapshot/get_text for "
        "reading content."
    ),
    meta={"module_id": MODULE_ID, "version": MODULE_VERSION},
)
async def screenshot(full_page: bool = False) -> dict:
    return await module.screenshot(full_page=full_page)


@mcp.tool(
    name="wait_for",
    description=(
        "Wait until an element reaches a state ('visible' | 'attached' | "
        "'hidden' | 'detached'). Use after an action that triggers async "
        "loading (e.g. clicking Search)."
    ),
    meta={"module_id": MODULE_ID, "version": MODULE_VERSION},
)
async def wait_for(selector: str, state: str = "visible", timeout_ms: int = 15000) -> dict:
    return await module.wait_for(selector=selector, state=state, timeout_ms=timeout_ms)


@mcp.tool(
    name="evaluate",
    description=(
        "Run arbitrary JavaScript in the page and return a JSON-serializable "
        "result. Powerful escape hatch — use for precise extraction (e.g. "
        "Array.from(document.querySelectorAll('.price')).map(e=>e.textContent))."
    ),
    meta={"module_id": MODULE_ID, "version": MODULE_VERSION},
)
async def evaluate(script: str) -> dict:
    return await module.evaluate(script=script)


@mcp.tool(
    name="go_back",
    description="Navigate to the previous page (browser back).",
    meta={"module_id": MODULE_ID, "version": MODULE_VERSION},
)
async def go_back() -> dict:
    return await module.go_back()


@mcp.tool(
    name="get_url_title",
    description="Return the current page URL and title. Use for orientation after redirects.",
    meta={"module_id": MODULE_ID, "version": MODULE_VERSION},
)
async def get_url_title() -> dict:
    return await module.get_url_title()


@mcp.tool(
    name="close",
    description=(
        "Reset the browser session (close page+context; recreated on next "
        "call). Call when the browsing task is done so the next agent starts "
        "clean."
    ),
    meta={"module_id": MODULE_ID, "version": MODULE_VERSION},
)
async def close() -> dict:
    return await module.close()
