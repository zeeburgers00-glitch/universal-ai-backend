import os
import re
from typing import Any

import httpx

from automation_worker.app import celery_app


ACTIONS = {
    "voice_tts": ("voice", "/v1/voice/tts", "VOICE_WORKER_URL", "VOICE_WORKER_API_KEY"),
    "voice_clone": ("voice", "/v1/voice/clone", "VOICE_WORKER_URL", "VOICE_WORKER_API_KEY"),
    "media_job": ("media", "/v1/media/jobs", "MEDIA_WORKER_URL", "MEDIA_WORKER_API_KEY"),
    "youtube_publish": ("youtube", "/v1/youtube/publish", "YOUTUBE_WORKER_URL", "YOUTUBE_WORKER_API_KEY"),
    "channel_action": ("channels", "/v1/channels/action", "CHANNEL_WORKER_URL", "CHANNEL_WORKER_API_KEY"),
    "desktop_action": ("desktop", "/v1/desktop/actions", "DESKTOP_AGENT_URL", "DESKTOP_AGENT_API_KEY"),
    "rea_inspect": ("rea", "/v1/rea/inspect", "REA_WORKER_URL", "REA_WORKER_API_KEY"),
}


def _validate_payload(action_name: str, payload: dict[str, Any], user_approved: bool) -> None:
    if action_name not in ACTIONS:
        raise ValueError(f"Unsupported workflow action {action_name!r}")
    if not isinstance(payload, dict) or len(str(payload)) > 50000:
        raise ValueError("Action payload must be a JSON object below 50 KB")
    # External posts/messages, REA inspections, and all computer actions are always approval-gated.
    if action_name in {"youtube_publish", "channel_action", "desktop_action", "rea_inspect"} and not user_approved:
        raise PermissionError(f"{action_name} requires explicit user approval")
    if action_name == "rea_inspect" and not payload.get("authorized_target_confirmed"):
        raise PermissionError("rea_inspect requires authorized_target_confirmed=true")
    if action_name == "youtube_publish" and not payload.get("video_asset_id"):
        raise ValueError("youtube_publish requires video_asset_id")
    if action_name == "voice_clone" and not (
        payload.get("speaker_consent_confirmed") and payload.get("speaker_consent_record_id")
    ):
        raise PermissionError("voice_clone requires explicit speaker consent and a consent record")
    if action_name == "channel_action" and not payload.get("target_id"):
        raise ValueError("channel_action requires a target_id")
    if action_name == "desktop_action" and not payload.get("paired_device_id"):
        raise ValueError("desktop_action requires a paired_device_id")


def _dispatch(action_name: str, payload: dict[str, Any], task_id: str, approved: bool) -> dict[str, Any]:
    _validate_payload(action_name, payload, approved)
    service, path, url_env, key_env = ACTIONS[action_name]
    base_url = os.getenv(url_env, "").strip().rstrip("/")
    api_key = os.getenv(key_env, "").strip()
    if not base_url or not api_key:
        return {
            "action": action_name, "status": "blocked_missing_worker",
            "required_environment": [url_env, key_env],
        }
    body = {**payload, "task_id": payload.get("task_id") or f"{task_id}-{action_name}", "user_approved": approved}
    timeout = httpx.Timeout(20, connect=8)
    try:
        with httpx.Client(timeout=timeout, follow_redirects=False) as client:
            response = client.post(
                base_url + path,
                json=body,
                headers={"Authorization": f"Bearer {api_key}", "X-Worker-Service": service},
            )
    except httpx.RequestError as exc:
        return {"action": action_name, "status": "dispatch_error", "error": type(exc).__name__}
    if response.status_code >= 400:
        return {"action": action_name, "status": "rejected", "http_status": response.status_code,
                "message": "Downstream worker rejected the action; inspect the downstream worker status/configuration."}
    try:
        result = response.json()
    except ValueError:
        result = {"message": "Downstream worker returned a non-JSON response"}
    return {"action": action_name, "status": "dispatched", "http_status": response.status_code, "result": result}


@celery_app.task(bind=True, name="automation_worker.dispatch_workflow", acks_late=True)
def dispatch_workflow(self, payload: dict[str, Any]) -> dict[str, Any]:
    task_id = str(self.request.id or "")
    if not re.fullmatch(r"[A-Za-z0-9_-]{8,120}", task_id):
        raise ValueError("Invalid workflow task ID")
    workflow = payload.get("workflow") or {}
    inputs = payload.get("inputs") or {}
    if not isinstance(workflow, dict) or not isinstance(inputs, dict):
        raise ValueError("Workflow and inputs must be objects")
    if workflow.get("id") != payload.get("workflow_id"):
        raise ValueError("Workflow ID mismatch")
    approved = bool(payload.get("user_approved"))
    dry_run = bool(payload.get("dry_run"))
    actions = inputs.get("actions") or []
    if not isinstance(actions, list) or len(actions) > 20:
        raise ValueError("inputs.actions must contain at most 20 actions")

    if not actions:
        return {
            "status": "plan_only",
            "task_id": task_id,
            "workflow_id": workflow.get("id"),
            "workflow_name": workflow.get("name"),
            "steps": [
                {"index": i, "step": step.get("id"), "agent_id": step.get("agent_id"),
                 "description": step.get("description"), "execution_status": "not_dispatched"}
                for i, step in enumerate(workflow.get("steps", []), start=1)
            ],
            "required_inputs": workflow.get("required_inputs", []),
            "next_step": "Review the workflow plan and supply explicit inputs.actions for the approved worker actions.",
            "note": "A workflow template describes intent; it does not automatically install dependencies, generate assets, or publish content.",
        }

    if dry_run:
        return {
            "status": "dry_run",
            "task_id": task_id,
            "workflow_id": workflow.get("id"),
            "actions": [{"index": i, "action": action.get("type"), "status": "not_dispatched"}
                        for i, action in enumerate(actions, start=1) if isinstance(action, dict)],
        }
    if not approved:
        raise PermissionError("Explicit user approval is required before workflow actions can dispatch")

    results = []
    for index, item in enumerate(actions, start=1):
        if not isinstance(item, dict):
            results.append({"index": index, "status": "invalid_action"})
            continue
        action_name = str(item.get("type", ""))
        action_payload = item.get("payload") or {}
        if not isinstance(action_payload, dict):
            results.append({"index": index, "action": action_name, "status": "invalid_payload"})
            continue
        try:
            result = _dispatch(action_name, action_payload, f"{task_id}-{index}", approved)
        except (ValueError, PermissionError) as exc:
            result = {"action": action_name, "status": "blocked", "reason": str(exc)}
        results.append({"index": index, **result})
    return {
        "status": "dispatched" if all(x.get("status") in {"dispatched", "blocked_missing_worker"} for x in results) else "completed_with_errors",
        "task_id": task_id,
        "workflow_id": workflow.get("id"),
        "results": results,
        "note": "Dispatched jobs may still be queued on their downstream workers; use each returned subtask ID to monitor completion.",
    }
