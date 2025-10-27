# planner/llm_planner.py
from openai import OpenAI
import json

client = OpenAI()


def generate_waypoints(app_name, task, context):
    """
    Generate a JSON plan (list of waypoints) describing UI steps
    to complete the user's task.
    """
    prompt = f"""
You are an expert automation planner for {app_name}.
Given the user's goal: "{task}", and documentation context below,
produce a concise JSON array of UI steps (called waypoints) that an automation
engine could follow to accomplish this task.

Each waypoint must include:
- "intent": what the step does
- "expected_state": how to know it succeeded

Context from docs:
{context}

Return ONLY valid JSON, no markdown.
    """

    response = client.chat.completions.create(
        model="gpt-4.1-nano-2025-04-14",
        messages=[{"role": "user", "content": prompt}],
        temperature=0.3,
    )

    text = response.choices[0].message.content.strip()

    # Ensure output is valid JSON
    try:
        plan = json.loads(text)
    except json.JSONDecodeError:
        print("Warning: invalid JSON returned, wrapping in list.")
        plan = [{"intent": "error_parsing_plan", "raw_output": text}]

    return plan
