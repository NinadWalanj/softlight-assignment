from runner.orchestrator import run_plan
import asyncio

if __name__ == "__main__":
    # Example defaults; adjust paths to your environment
    asyncio.run(
        run_plan(
            app_name="linear",
            start_url="https://linear.app",
            plan_path="plans/linear/view_project.json",
            dataset_dir="dataset/linear/view_project",
            headless=False,
            slow_mo=200,
        )
    )
