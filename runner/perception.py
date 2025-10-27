# runner/perception.py
import os
import json
import asyncio
from playwright.async_api import Page

# Reuse your selectors / heuristics
INTERACTIVE_SELECTORS = [
    # native interactive elements
    "button",
    "a[href]",
    "input",
    "textarea",
    "select",
    "summary",
    # ARIA roles
    "[role=button]",
    "[role=link]",
    "[role=menuitem]",
    "[role=option]",
    "[role=tab]",
    "[role=checkbox]",
    "[role=switch]",
    "[role=dialog]",
    # custom/interactive
    "[tabindex]:not([tabindex='-1'])",
    "[aria-haspopup]",
    "[contenteditable=true]",
    # design system helpers
    "[data-testid]",
    "[data-tooltip]",
    "[title]",
]


async def _textish(el):
    """Return the most informative visible label for an element (async)."""
    aria = await el.get_attribute("aria-label") or ""
    title = await el.get_attribute("title") or ""
    txt = (await el.inner_text() or "").strip()
    return aria or title or txt


async def _wait_for_ui_ready(
    page: Page, timeout_ms: int = 6000, min_candidates: int = 8
):
    """
    Wait for load/network idle, then ensure we have a minimum number of interactive
    candidates before we snapshot. This prevents Step 1 'only 1 element' captures.
    """
    try:
        # Let network & DOM settle
        await page.wait_for_load_state("domcontentloaded", timeout=timeout_ms)
        try:
            await page.wait_for_load_state("networkidle", timeout=timeout_ms)
        except Exception:
            # networkidle may not always fire; that's fine
            pass
    except Exception:
        pass

    # Poll for enough interactive nodes using our selector set
    combined = ", ".join(INTERACTIVE_SELECTORS)
    deadline = page.context._loop.time() + (timeout_ms / 1000)
    last_count = 0

    while page.context._loop.time() < deadline:
        try:
            count = await page.evaluate(
                f"document.querySelectorAll({json.dumps(combined)}).length"
            )
            last_count = count
            if count >= min_candidates:
                return
        except Exception:
            pass
        await asyncio.sleep(0.15)

    # No hard fail — proceed with whatever we have, but log
    print(
        f"ℹ️ UI-ready threshold not met (found {last_count} < {min_candidates}); proceeding."
    )


async def _pre_reveal(page: Page):
    """
    Small nudge to reveal lazy/overflow UI (generic, app-agnostic):
    - scroll to top, then down a bit
    - hover near common sidebar/menu triggers (best-effort, safe if missing)
    """
    try:
        await page.evaluate("window.scrollTo(0, 0)")
        await page.mouse.wheel(0, 600)
        await asyncio.sleep(0.1)
        await page.mouse.wheel(0, -600)
    except Exception:
        pass

    # Best-effort hovers that often expand sidebars/menus
    for sel in [
        "[aria-label*=Workspace i], [aria-label*=workspace i], [aria-label*=menu i]",
        "button:has-text('Workspace')",
        "[data-testid*=sidebar]",
    ]:
        try:
            loc = page.locator(sel)
            if await loc.count() > 0:
                await loc.first.hover(timeout=500)
                await asyncio.sleep(0.1)
        except Exception:
            continue


async def _collect_interactive(page: Page):
    """Collect visible interactive elements with bounding boxes (async)."""
    combined = ", ".join(INTERACTIVE_SELECTORS)
    elements = await page.query_selector_all(combined)

    seen = set()
    perceived = []

    for el in elements:
        try:
            if not await el.is_visible():
                continue

            box = await el.bounding_box() or {}
            if not box or box.get("width", 0) < 2 or box.get("height", 0) < 2:
                continue

            tag = await el.evaluate("n => n.tagName.toLowerCase()")
            role = await el.get_attribute("role")
            aria = await el.get_attribute("aria-label") or ""
            title = await el.get_attribute("title") or ""
            tooltip = await el.get_attribute("data-tooltip") or ""
            textish = await _textish(el)

            # require at least some label signal
            if not (textish or tooltip):
                continue

            key = (
                tag,
                role,
                textish,
                aria,
                title,
                tooltip,
                round(box.get("x", 0)),
                round(box.get("y", 0)),
            )
            if key in seen:
                continue
            seen.add(key)

            perceived.append(
                {
                    "tag": tag,
                    "role": role,
                    "text": textish,
                    "aria_label": aria,
                    "title": title,
                    "tooltip": tooltip,
                    "visible": True,
                    "x": box.get("x"),
                    "y": box.get("y"),
                    "width": box.get("width"),
                    "height": box.get("height"),
                }
            )
        except Exception:
            continue

    print(f"Perceived {len(perceived)} visible interactive elements.")
    return perceived


async def capture_perception(page: Page, app_name: str, step_id: int, dataset_dir: str):
    """
    Capture the current UI state for this step:
      - wait for UI to be ready & reveal common areas
      - AX tree → step_<n>/ax_tree.json
      - interactive elements → step_<n>/perception.json
      - screenshot → step_<n>/ui.png
    """
    # 0) Ensure UI is stable and populated
    await _wait_for_ui_ready(page)
    await _pre_reveal(page)

    step_dir = os.path.join(dataset_dir, f"step_{step_id}")
    os.makedirs(step_dir, exist_ok=True)

    ax_path = os.path.join(step_dir, "ax_tree.json")
    perception_path = os.path.join(step_dir, "perception.json")
    # screenshot_path = os.path.join(step_dir, "ui.png")

    # Accessibility snapshot (full, not just interesting)
    try:
        ax_tree = await page.accessibility.snapshot(root=None, interesting_only=False)
        with open(ax_path, "w", encoding="utf-8") as f:
            json.dump(ax_tree, f, indent=2, ensure_ascii=False)
        print(f"AX snapshot saved: {ax_path}")
    except Exception as e:
        print(f"Failed to dump AX tree: {e}")

    # Screenshot of current state
    # await page.screenshot(path=screenshot_path, full_page=True)
    # print(f"Screenshot saved: {screenshot_path}")

    # Perception (interactive elements)
    perceived = await _collect_interactive(page)
    with open(perception_path, "w", encoding="utf-8") as f:
        json.dump(perceived, f, indent=2, ensure_ascii=False)
    print(f"Perception snapshot saved: {perception_path}")

    return perceived
