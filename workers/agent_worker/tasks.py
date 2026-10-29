import json
import os
import re
from typing import Any

import httpx

from agent_worker.app import celery_app

ALLOWED_ACTIONS = {
    "draft_content",
    "research",
    "voice_tts",
    "media_job",
    "youtube_publish",
    "channel_action",
    "desktop_action",
    "rea_call",
    "coding_plan",
    "knowledge_query",
    "approval_required",
}


def _extract_json(content: str) -> dict[str, Any]:
    text = content.strip()
    if text.startswith("```"):
        lines = text.splitlines()
        if lines and lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].startswith("```"):
            lines = lines[:-1]
        text = "\n".join(lines).strip()
    start, end = text.find("{"), text.rfind("}")
    if start < 0 or end <= start:
        raise ValueError("Model did not return a JSON object")
    result = json.loads(text[start:end + 1])
    if not isinstance(result, dict):
        raise ValueError("Model result must be a JSON object")
    return result


def _model_config() -> tuple[str, str, str]:
    base = (os.getenv("AGENT_MODEL_BASE_URL") or os.getenv("AI_BASE_URL") or "").strip().rstrip("/")
    key = (os.getenv("AGENT_MODEL_API_KEY") or os.getenv("AI_API_KEY") or "").strip()
    model = (os.getenv("AGENT_DEFAULT_MODEL") or os.getenv("AI_DEFAULT_MODEL") or "").strip()
    if not base or not key or not model:
        raise RuntimeError("Set AGENT_MODEL_BASE_URL/AGENT_MODEL_API_KEY/AGENT_DEFAULT_MODEL or the shared AI provider equivalents")
    if not base.startswith("https://") and not (
        os.getenv("AGENT_ALLOW_INSECURE_HTTP", "").lower() == "true" and base.startswith("http://")
    ):
        raise RuntimeError("Agent model URL must use HTTPS unless local development explicitly enables HTTP")
    return base, key, model


@celery_app.task(bind=True, name="agent_worker.plan_agent", acks_late=True)
def plan_agent(self, payload: dict[str, Any]) -> dict[str, Any]:
    task_id = str(self.request.id or "")
    if not re.fullmatch(r"[A-Za-z0-9_-]{8,120}", task_id):
        raise ValueError("Invalid task ID")
    agent = payload.get("agent") or {}
    objective = str(payload.get("objective") or "").strip()
    inputs = payload.get("inputs") or {}
    if not objective or len(objective) > 12000:
        raise ValueError("Objective is required and has a 12000-character limit")
    if not isinstance(agent, dict) or not isinstance(inputs, dict):
        raise ValueError("Agent and inputs must be JSON objects")

    base, api_key, model = _model_config()
    endpoint = base if base.endswith("/chat/completions") else f"{base}/chat/completions"
    system_prompt = (
        "You are the planning component of Universal AI Backend, a safety-bounded agent system. "
        "Create a useful, practical plan for the user's objective. Do not claim you performed actions. "
        "Do not generate arbitrary shell commands, executable code, credential requests, or external URLs as tools. "
        "Do not execute anything. Side-effectful actions must be marked requires_approval=true. "
        "Output JSON only in the schema: "
        "{\"summary\": string, \"assumptions\": [string], \"steps\": [{\"id\": string, "
        "\"action\": one of "
        + ", ".join(sorted(ALLOWED_ACTIONS))
        + ", \"description\": string, \"inputs\": object, \"requires_approval\": boolean, "
        "\"expected_output\": string}], \"risks\": [string], \"missing_inputs\": [string]}. "
        "Keep plans to at most 12 steps. If important inputs are absent, list them in missing_inputs."
    )
    user_payload = {
        "agent": {
            "id": agent.get("id", payload.get("agent_id")),
            "name": agent.get("name"),
            "mission": agent.get("mission"),
            "capabilities": agent.get("capabilities", []),
            "risk_level": agent.get("risk_level", "unknown"),
            "human_approval_rules": agent.get("human_approval_rules", ""),
        },
        "objective": objective,
        "inputs": inputs,
        "user_approved": bool(payload.get("user_approved")),
        "dry_run": bool(payload.get("dry_run", True)),
    }
    response = httpx.post(
        endpoint,
        json={
            "model": model,
            "temperature": 0.2,
            "max_tokens": 3000,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": json.dumps(user_payload, ensure_ascii=False)},
            ],
        },
        headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
        timeout=httpx.Timeout(75.0, connect=10.0),
        follow_redirects=False,
    )
    response.raise_for_status()
    data = response.json()
    content = data.get("choices", [{}])[0].get("message", {}).get("content", "")
    plan = _extract_json(str(content))
    steps = plan.get("steps")
    if not isinstance(steps, list) or len(steps) > 12:
        raise ValueError("Agent plan must contain at most 12 steps")
    validated_steps = []
    for index, step in enumerate(steps):
        if not isinstance(step, dict):
            raise ValueError("Every step must be an object")
        action = str(step.get("action", ""))
        if action not in ALLOWED_ACTIONS:
            raise ValueError(f"Planner produced unsupported action type at step {index}")
        inputs_value = step.get("inputs", {})
        if not isinstance(inputs_value, dict):
            raise ValueError(f"Step {index} inputs must be an object")
        validated_steps.append({
            "id": str(step.get("id") or f"step-{index + 1}")[:100],
            "action": action,
            "description": str(step.get("description") or "")[:2000],
            "inputs": inputs_value,
            "requires_approval": bool(step.get("requires_approval")) or action in {
                "youtube_publish", "channel_action", "desktop_action", "rea_call",
            },
            "expected_output": str(step.get("expected_output") or "")[:1000],
            "execution_status": "not_executed",
        })
    return {
        "status": "plan_created",
        "task_id": task_id,
        "agent_id": payload.get("agent_id"),
        "summary": str(plan.get("summary") or "")[:3000],
        "assumptions": [str(x)[:500] for x in (plan.get("assumptions") or [])[:20]],
        "steps": validated_steps,
        "risks": [str(x)[:1000] for x in (plan.get("risks") or [])[:20]],
        "missing_inputs": [str(x)[:500] for x in (plan.get("missing_inputs") or [])[:30]],
        "execution_mode": "plan_only",
        "user_approved": bool(payload.get("user_approved")),
        "note": "No step has been executed. Send reviewed approved actions to dedicated endpoints after inspecting the plan.",
    }
