# runner/verifier.py
import re
from typing import Optional
from playwright.async_api import Page, Locator

# ---------- quoted helpers ----------
_QUOTED = re.compile(r"'([^']{1,200})'|\"([^\"]{1,200})\"")
def _extract_all_quoted(s: str) -> list[str]:
    return [(m.group(1) or m.group(2)).strip() for m in _QUOTED.finditer(s or "")]

# ---------- low-level element helpers ----------
async def _dialog(page: Page) -> Optional[Locator]:
    dlg = page.get_by_role("dialog")
    if await dlg.count() > 0:
        return dlg.first
    return None

async def _first_textbox(scope: Locator | Page) -> Optional[Locator]:
    try:
        tb = scope.get_by_role("textbox").first
        if await tb.count() > 0:
            return tb
    except Exception:
        pass
    try:
        tb = scope.locator("input[type='text'], textarea").first
        if await tb.count() > 0:
            return tb
    except Exception:
        pass
    try:
        tb = scope.locator("[contenteditable='true']").first
        if await tb.count() > 0:
            return tb
    except Exception:
        pass
    return None

# ---------- primitive verifications ----------
async def verify_dialog_open(page: Page, must_contain: str | None = None, timeout_ms: int = 3000) -> bool:
    try:
        await page.wait_for_selector("[role='dialog'], div[role='dialog']", timeout=timeout_ms)
    except Exception:
        return False
    if not must_contain:
        return True
    try:
        dlg = await _dialog(page)
        if not dlg:
            return False
        txt = (await dlg.inner_text() or "").lower()
        return must_contain.lower() in txt
    except Exception:
        return False

async def verify_text_visible(page: Page, text: str, timeout_ms: int = 2000) -> bool:
    # exact first
    try:
        loc = page.get_by_text(text, exact=True)
        if await loc.count() > 0:
            await loc.first.wait_for(state="visible", timeout=timeout_ms)
            return True
    except Exception:
        pass
    # contains fallback
    try:
        loc = page.get_by_text(text)
        if await loc.count() > 0:
            await loc.first.wait_for(state="visible", timeout=timeout_ms)
            return True
    except Exception:
        pass
    return False

async def verify_textbox_value(page: Page, expected: str) -> bool:
    dlg = await _dialog(page)
    scope = dlg if dlg else page
    tb = await _first_textbox(scope)
    if not tb:
        return False

    # input value first
    try:
        val = await tb.input_value(timeout=1000)
        if val and expected.lower() in val.lower():
            return True
    except Exception:
        pass

    # contenteditable fallback
    try:
        txt = (await tb.inner_text() or "").strip()
        if txt and expected.lower() in txt.lower():
            return True
    except Exception:
        pass

    return False

async def verify_element_exists(page: Page, role: str, name: str | None = None, timeout_ms: int = 2000) -> bool:
    try:
        loc = page.get_by_role(role, name=name) if name else page.get_by_role(role)
        if await loc.count() > 0:
            await loc.first.wait_for(state="visible", timeout=timeout_ms)
            return True
    except Exception:
        pass
    return False

async def verify_url_contains(page: Page, fragment: str) -> bool:
    try:
        url = page.url or ""
        return fragment.lower() in url.lower()
    except Exception:
        return False

# ---------- generic router ----------
async def verify_step(page: Page, intent: str, expected_state: str) -> bool:
    """
    Generic verification:
      - If expected_state mentions dialog/modal -> verify dialog (optionally containing quoted text)
      - If mentions field/input/textbox + contains/value -> verify textbox contains quoted value
      - If mentions url/location/path -> verify URL contains quoted fragment
      - If mentions button/link/menuitem/tab + quoted -> verify element exists by role+name
      - If it says visible/appears/shown/listed and has quoted text -> verify text visible
      - Else: fallback to quoted text on page (if present), otherwise True
    """
    es = (expected_state or "").strip()
    il = (intent or "").lower()
    el = es.lower()
    quoted = _extract_all_quoted(es) or _extract_all_quoted(intent)

    # 1) Dialog / Modal open
    if any(k in el for k in ["dialog", "modal", "prompt"]):
        return await verify_dialog_open(page, must_contain=quoted[0] if quoted else None)

    # 2) URL checks
    if any(k in el for k in ["url", "location", "path", "navigate", "navigated"]):
        if quoted:
            return await verify_url_contains(page, quoted[0])

    # 3) Field/Input/Textbox value checks
    if any(k in el for k in ["field", "input", "textbox", "editor"]) and any(k in el for k in ["contains", "set to", "value", "filled"]):
        target = quoted[0] if quoted else None
        if target:
            return await verify_textbox_value(page, target)
        # if no quoted value, at least ensure a textbox exists
        tb = await _first_textbox(page)
        return tb is not None

    # 4) Element existence with role+name (button/link/menuitem/tab)
    if any(k in el for k in ["button", "link", "menuitem", "tab"]) and quoted:
        role = "button" if "button" in el else "link" if "link" in el else "menuitem" if "menuitem" in el else "tab" if "tab" in el else "button"
        name = quoted[0]
        return await verify_element_exists(page, role=role, name=name)

    # 5) Generic “visible/appears/shown/listed/present” text
    if any(k in el for k in ["visible", "appears", "shown", "displayed", "listed", "present"]) and quoted:
        return await verify_text_visible(page, quoted[0])

    # 6) If we have any quoted text, try to see it on screen
    if quoted:
        for q in quoted:
            if await verify_text_visible(page, q):
                return True
        return False

    # 7) Last resort: if nothing to assert, don't block the pipeline
    return True
