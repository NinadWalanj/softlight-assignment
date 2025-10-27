# runner/executor.py
import os
import re
import asyncio
from typing import Dict, Optional, Tuple
from playwright.async_api import Page, Locator

# --------- Quoted parsing (supports 'single' and "double") ---------
LABEL_QUOTED_RE = re.compile(r"'([^']{1,200})'|\"([^\"]{1,200})\"")
ARIA_LABEL_RE = re.compile(r"aria-label=['\"]([^'\"]+)['\"]", re.I)


def _extract_quoted(intent: str) -> Optional[str]:
    m = LABEL_QUOTED_RE.search(intent)
    if not m:
        return None
    return (m.group(1) or m.group(2)).strip()


def _extract_aria_label(intent: str) -> Optional[str]:
    m = ARIA_LABEL_RE.search(intent or "")
    return m.group(1).strip() if m else None


# --------- Intent classification ---------
def _classify_action(intent: str) -> Tuple[str, Optional[str], Optional[str]]:
    """
    Returns: (action, value, label)
      action: "click" | "fill" | "open"
      value: for fills (e.g., quoted content or defaults)
      label: preferred UI label to target for clicks (quoted in the intent)
    """
    intent_l = intent.lower()
    quoted = _extract_quoted(intent)

    if any(k in intent_l for k in ["fill", "enter", "type", "input"]):
        value = quoted or ("Demo Project" if "name" in intent_l else "Test Value")
        return "fill", value, None

    if any(k in intent_l for k in ["open", "navigate", "go to"]):
        return "open", None, quoted

    if any(
        k in intent_l
        for k in [
            "click",
            "press",
            "tap",
            "select",
            "choose",
            "submit",
            "create",
            "save",
        ]
    ):
        return "click", None, quoted

    return "click", None, quoted


# --------- Utilities ---------
async def _ensure_dir(path: str):
    os.makedirs(path, exist_ok=True)


async def _center_of(el: Dict) -> Tuple[float, float]:
    x = float(el.get("x", 0.0))
    y = float(el.get("y", 0.0))
    w = float(el.get("width", 0.0))
    h = float(el.get("height", 0.0))
    return x + max(w, 1) / 2.0, y + max(h, 1) / 2.0


# --------- Handle resolvers / click helpers ---------
async def _try_click_by_label(page: Page, label: str) -> bool:
    # Prefer semantic roles first, then text
    candidates = [
        page.get_by_role("button", name=label),
        page.get_by_role("link", name=label),
        page.get_by_text(label, exact=True),
        page.get_by_text(label),
    ]
    for loc in candidates:
        try:
            if await loc.count() > 0:
                await loc.first.click(timeout=4000)
                return True
        except Exception:
            continue
    return False


async def _try_click_by_aria_label(page: Page, aria_label: str) -> bool:
    # Exact aria-label
    try:
        loc = page.locator(f"[aria-label='{aria_label}']")
        if await loc.count() > 0:
            await loc.first.click(timeout=4000)
            return True
    except Exception:
        pass
    # Contains fallback
    try:
        loc = page.locator(f"[aria-label*='{aria_label}']")
        if await loc.count() > 0:
            await loc.first.click(timeout=4000)
            return True
    except Exception:
        pass
    return False


async def _try_click_menuitem_named(page: Page, name: str) -> bool:
    try:
        loc = page.get_by_role("menuitem", name=name)
        if await loc.count() > 0:
            await loc.first.click(timeout=4000)
            return True
    except Exception:
        pass
    return False


async def _try_get_handle_by_role(page: Page, el: Dict) -> Optional[Locator]:
    name = (el.get("text") or "").strip()
    tag = (el.get("tag") or "").lower()
    role = (el.get("role") or "").lower()
    if role == "button" or tag == "button":
        return (
            page.get_by_role("button", name=name)
            if name
            else page.get_by_role("button")
        ).first
    if role == "link" or tag == "a":
        return (
            page.get_by_role("link", name=name) if name else page.get_by_role("link")
        ).first
    if role == "dialog":
        return page.get_by_role("dialog").first
    return None


async def _try_get_handle_by_text(page: Page, el: Dict) -> Optional[Locator]:
    name = (el.get("text") or "").strip()
    if not name:
        return None
    try:
        return page.get_by_text(name, exact=True).first
    except Exception:
        pass
    try:
        return page.get_by_text(name).first
    except Exception:
        return None


# --------- Textbox resolver for fills ---------
LABEL_RE = re.compile(r"(project\s*name|name|title)", re.I)
PLACEHOLDER_RE = re.compile(r"(project.*name|name|title)", re.I)


async def _resolve_textbox_scope(scope: Locator) -> Optional[Locator]:
    try:
        loc = scope.get_by_label(LABEL_RE).first
        if await loc.count() > 0:
            return loc
    except Exception:
        pass
    try:
        loc = scope.get_by_placeholder(PLACEHOLDER_RE).first
        if await loc.count() > 0:
            return loc
    except Exception:
        pass
    try:
        loc = scope.get_by_role("textbox").first
        if await loc.count() > 0:
            return loc
    except Exception:
        pass
    try:
        loc = scope.locator("input[type='text'], textarea").first
        if await loc.count() > 0:
            return loc
    except Exception:
        pass
    try:
        loc = scope.locator("[contenteditable='true']").first
        if await loc.count() > 0:
            return loc
    except Exception:
        pass
    return None


async def _resolve_textbox(page: Page) -> Tuple[Optional[Locator], str]:
    try:
        dlg = page.get_by_role("dialog")
        if await dlg.count() > 0:
            loc = await _resolve_textbox_scope(dlg)
            if loc:
                return loc, "dialog"
    except Exception:
        pass
    loc = await _resolve_textbox_scope(page)
    if loc:
        return loc, "page"
    return None, "none"


# --------- Main entrypoint ---------
async def execute_action(
    page: Page, element: Dict, intent: str, step_id: int, dataset_dir: str
) -> Dict:
    step_dir = os.path.join(dataset_dir, f"step_{step_id}")
    await _ensure_dir(step_dir)

    before_path = os.path.join(step_dir, "before.png")
    after_path = os.path.join(step_dir, "after.png")

    await page.screenshot(path=before_path, full_page=True)

    action, value, label = _classify_action(intent)
    aria_label = _extract_aria_label(intent)

    # small nudge to stabilize layout
    try:
        await page.mouse.wheel(0, 0)
    except Exception:
        pass

    try:
        if action in ("click", "open"):
            # 1) Explicit aria-label wins (e.g., aria-label='Project actions')
            if aria_label and await _try_click_by_aria_label(page, aria_label):
                pass
            # 2) Menu item clicks (e.g., 'Delete' inside a context menu)
            elif label and await _try_click_menuitem_named(page, label):
                pass
            # 3) Visible label via role/text (buttons/links/text)
            elif label and await _try_click_by_label(page, label):
                pass
            else:
                # 4) Fallback to handle from perception or coordinate click
                handle = await _try_get_handle_by_role(
                    page, element
                ) or await _try_get_handle_by_text(page, element)
                if handle:
                    await handle.click(timeout=4000)
                else:
                    cx, cy = await _center_of(element)
                    await page.mouse.click(cx, cy)

        elif action == "fill":
            # Ensure dialog (if any) is present, then find the textbox regardless of located element
            try:
                await page.wait_for_selector(
                    "[role='dialog'], div[role='dialog']", timeout=3000
                )
            except Exception:
                pass

            textbox, _scope = await _resolve_textbox(page)
            if not textbox:
                raise RuntimeError("No textbox found to fill.")

            try:
                await textbox.click(timeout=3000)
            except Exception:
                pass

            # Try fill; fallback to typing (contenteditable)
            try:
                await textbox.fill(value or "Demo Project", timeout=4000)
            except Exception:
                await page.keyboard.type(value or "Demo Project", delay=20)

        # allow UI to update
        await asyncio.sleep(2.0)
        await page.screenshot(path=after_path, full_page=True)

        return {
            "status": "success",
            "action": action,
            "intent": intent,
            "label": label,
            "aria_label": aria_label,
            "used_text": element.get("text"),
            "tag": element.get("tag"),
        }

    except Exception as e:
        try:
            await page.screenshot(path=after_path, full_page=True)
        except Exception:
            pass
        return {
            "status": "fail",
            "action": action,
            "intent": intent,
            "label": label,
            "aria_label": aria_label,
            "error": str(e),
            "used_text": element.get("text"),
            "tag": element.get("tag"),
        }
