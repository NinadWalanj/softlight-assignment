from planner.cache_manager import get_or_generate_plan

# Define your test query
app_name = "notion"
task = "create page"

# Generate (or load cached) plan
plan = get_or_generate_plan(app_name, task)

# Print the result nicely
print("\nGenerated Plan:\n")
for i, step in enumerate(plan, start=1):
    print(f"Step {i}: {step['intent']}")
    print(f"    → Expected State: {step.get('expected_state', 'N/A')}\n")
