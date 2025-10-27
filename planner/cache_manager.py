# planner/cache_manager.py
import os, json
from planner.vector_db import get_relevant_chunks
from planner.llm_planner import generate_waypoints

PLANS_DIR = "plans"
os.makedirs(PLANS_DIR, exist_ok=True)


def get_or_generate_plan(app_name, task):
    """Load plan from cache if it exists, else generate via LLM and save."""
    task_sanitized = task.lower().replace(" ", "_")
    plan_path = os.path.join(PLANS_DIR, app_name, f"{task_sanitized}.json")
    print(f"🔍 Checking cache at: {plan_path}")
    os.makedirs(os.path.dirname(plan_path), exist_ok=True)

    if os.path.exists(plan_path):
        with open(plan_path, "r", encoding="utf-8") as f:
            print(f"Loaded cached plan for {app_name}:{task}")
            return json.load(f)

    # No cached plan → retrieve docs + call LLM
    context_chunks = get_relevant_chunks(app_name, task, top_k=3)
    combined_context = "\n\n".join(context_chunks)

    print(f"Generating new plan for {app_name}:{task}")
    plan = generate_waypoints(app_name, task, combined_context)

    with open(plan_path, "w", encoding="utf-8") as f:
        json.dump(plan, f, indent=2)
    print(f"Plan saved to {plan_path}")
    return plan
