# runner/orchestrator.py
import os
import json
import asyncio
from typing import Optional
from playwright.async_api import async_playwright

from runner.session_manager import load_session
from runner.perception import (
    capture_perception,
)  # async, saves step_x/perception.json + ui.png + ax_tree.json
from runner.locator import (
    locate_element_for_intent,
)  # expects (intent, perception_path)
from runner.executor import execute_action  # async
from runner.verifier import verify_step
from runner.recovery import recover_step


async def run_plan(
    app_name: str,
    start_url: str,
    plan_path: str,
    dataset_dir: str,
    headless: bool = False,
    slow_mo: int = 200,
    viewport: Optional[dict] = None,
):
    """
    Orchestrates the Path-2 loop:
      For each step in the plan:
        1) Perception (capture DOM + screenshot)
        2) Locator (choose element using perception.json)
        3) Executor (perform action; saves before/after)
        4) Verifier (generic checks inferred from expected_state/intent)
    """
    os.makedirs(dataset_dir, exist_ok=True)

    # Load plan
    with open(plan_path, "r", encoding="utf-8") as f:
        plan = json.load(f)

    # Load saved session (auth)
    session_path = load_session(app_name)

    if viewport is None:
        viewport = {"width": 1600, "height": 900}

    print(f"\nStarting run for {app_name}")
    print(f"Start URL: {start_url}")
    print(f"Plan: {plan_path}")
    print(f"Dataset dir: {dataset_dir}")

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=headless, args=["--start-maximized"])
        context = await browser.new_context(storage_state=session_path, viewport=None)
        page = await context.new_page()

        # Navigate to the start URL once; later steps will mutate UI in-place
        await page.goto(start_url)

        # Try to wait for main workspace if present
        try:
            await page.wait_for_selector("main", timeout=20000)
            print("Workspace loaded successfully.")
        except Exception:
            print("main workspace selector not found; continuing.")

        # Execute plan step-by-step
        for step_idx, step in enumerate(plan, start=1):
            intent = step.get("intent") or step.get("step", "")
            expected = step.get("expected_state", "")

            print(f"\n— — — — — — — — — — — — — — — — —")
            print(f"Step {step_idx}: {intent}")
            print(f"   Expected: {expected}")

            # 1) Perception (saves files under dataset/<app>/step_<n>/)
            perception_data = await capture_perception(
                page=page, app_name=app_name, step_id=step_idx, dataset_dir=dataset_dir
            )

            # Path for this step's artifacts
            step_dir = os.path.join(dataset_dir, f"step_{step_idx}")
            os.makedirs(step_dir, exist_ok=True)
            perception_path = os.path.join(step_dir, "perception.json")

            # 2) Locator
            element = locate_element_for_intent(intent, perception_path)
            if not element:
                print(f"Locator: no suitable element for this intent.")
                # Record step metadata even on failure
                with open(
                    os.path.join(step_dir, "step.json"), "w", encoding="utf-8"
                ) as f:
                    json.dump(
                        {
                            "step_id": step_idx,
                            "intent": intent,
                            "expected_state": expected,
                            "executor_status": "skipped_no_element",
                            "verified": False,
                        },
                        f,
                        indent=2,
                    )
                continue

            # 3) Executor (saves before/after in the same step dir)
            result = await execute_action(
                page=page,
                element=element,
                intent=intent,
                step_id=step_idx,
                dataset_dir=dataset_dir,
            )

            status = result.get("status", "unknown")
            action = result.get("action", "n/a")
            print(f"Executor: {status} | action={action}")

            # 4) Verifier
            ok = await verify_step(page, intent, expected)
            print(f"Verify: {'pass' if ok else 'fail'}")

            # Persist per-step metadata (include recovery info)
            with open(os.path.join(step_dir, "step.json"), "w", encoding="utf-8") as f:
                json.dump(
                    {
                        "step_id": step_idx,
                        "intent": intent,
                        "expected_state": expected,
                        "executor_status": status,
                        "verified": bool(ok),
                        "executor_meta": {
                            "action": action,
                            "used_text": result.get("used_text"),
                            "tag": result.get("tag"),
                            "label": result.get("label"),
                            "aria_label": result.get("aria_label"),
                            "error": result.get("error"),
                        },
                    },
                    f,
                    indent=2,
                )

            # Small pause between steps to let UI settle
            await asyncio.sleep(1.0)

        await browser.close()
        print("\nPlan execution completed.\n")
