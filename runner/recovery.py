# runner/recovery.py
import os
import asyncio
from typing import Dict, Optional, List
from playwright.async_api import Page

from runner.perception import capture_perception
from runner.locator import locate_element_for_intent
try:
    # optional if you added it
    from runner.locator import locate_top_candidates
except Exception:
    locate_top_candidates = None  # type: ignore

from runner.executor import execute_action

# ------------------ UI nudges ------------------

async def _gentle_stabilize(page: Page):
    # Let microtasks settle
    await asyncio.sleep(0.25)
    # Tiny scroll to trigger lazy content
    try:
        await page.evaluate("window.scrollTo(0, 0)")
        await page.mouse.wheel(0, 600)
        await asyncio.sleep(0.1)
        await page.mouse.wheel(0, -300)
    except Exception:
        pass

async def _close_easy_popups(page: Page):
    # Common tour/toast buttons; best-effort
    for label in ["Close", "Dismiss", "Got it", "Skip"]:
        try:
            loc = page.get_by_role("button", name=label)
            if await loc.count() > 0:
                await loc.first.click(timeout=600)
                await asyncio.sleep(0.15)
        except Exception:
            continue

async def _wait_if_dialog_expected(page: Page, intent: str, expected: str):
    text = f"{intent} {expected}".lower()
    if any(k in text for k in ["dialog", "modal", "prompt"]):
        try:
            await page.wait_for_selector("[role='dialog'], div[role='dialog']", timeout=2500)
        except Exception:
            pass

# ------------------ Recovery core ------------------

async def recover_step(
    page: Page,
    app_name: str,
    dataset_dir: str,
    step_idx: int,
    intent: str,
    expected: str,
    previous_element: Optional[Dict],
    attempt: int = 1,
    max_attempts: int = 2,
) -> Dict:
    """
    Attempt to recover a failed step by:
      1) stabilizing UI, closing popups, dialog wait if relevant
      2) re-perception
      3) trying an alternative candidate (top-K) or re-running best
    Returns: {"recovered": bool, "attempts": int, "result": <executor result or None>}
    """
    if attempt > max_attempts:
        return {"recovered": False, "attempts": attempt - 1, "result": None}

    # 1) Stabilize + optional dialog wait + close popups
    await _gentle_stabilize(page)
    await _wait_if_dialog_expected(page, intent, expected)
    await _close_easy_popups(page)

    # 2) Re-perceive (fresh elements)
    perception = await capture_perception(
        page=page,
        app_name=app_name,
        step_id=step_idx,             # reuses the same step folder (overwrites perception.json and ui.png)
        dataset_dir=dataset_dir
    )
    step_dir = os.path.join(dataset_dir, f"step_{step_idx}")
    perception_path = os.path.join(step_dir, "perception.json")

    # 3) Try again: prefer alternates if available
    candidates: List[Dict] = []
    if locate_top_candidates:
        try:
            candidates = locate_top_candidates(intent, perception_path, k=5) or []
        except Exception:
            candidates = []
    if not candidates:
        # Fallback to single best
        el = locate_element_for_intent(intent, perception_path)
        candidates = [el] if el else []

    # If we had a previous element, avoid selecting the exact same one first
    def _is_same(a: Optional[Dict], b: Optional[Dict]) -> bool:
        if not a or not b:
            return False
        ax, ay, aw, ah = a.get("x"), a.get("y"), a.get("width"), a.get("height")
        bx, by, bw, bh = b.get("x"), b.get("y"), b.get("width"), b.get("height")
        return (ax, ay, aw, ah) == (bx, by, bw, bh)

    ordered = []
    for el in candidates:
        if not _is_same(previous_element, el):
            ordered.append(el)
    # ensure at least something
    if not ordered and candidates:
        ordered = candidates

    # Try each candidate quickly
    for idx, el in enumerate(ordered):
        try:
            result = await execute_action(
                page=page,
                element=el,
                intent=intent,
                step_id=step_idx,
                dataset_dir=dataset_dir
            )
            if result.get("status") == "success":
                return {"recovered": True, "attempts": attempt, "result": result}
        except Exception:
            continue

    # Optional: one more pass after pressing Escape to close random overlays
    try:
        await page.keyboard.press("Escape")
        await asyncio.sleep(0.2)
    except Exception:
        pass

    # Recurse once more if allowed
    return await recover_step(
        page=page,
        app_name=app_name,
        dataset_dir=dataset_dir,
        step_idx=step_idx,
        intent=intent,
        expected=expected,
        previous_element=previous_element,
        attempt=attempt + 1,
        max_attempts=max_attempts,
    )
