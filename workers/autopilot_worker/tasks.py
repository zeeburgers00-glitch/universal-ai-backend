from __future__ import annotations

import concurrent.futures
import hashlib
import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import httpx

from autopilot_worker.app import celery_app

ROOT = Path(__file__).resolve().parents[1]
FLEET_PATH = ROOT / "catalog" / "youtube_agent_fleet.json"
SUPABASE_URL = os.getenv("SUPABASE_URL", "").strip().rstrip("/")
SUPABASE_KEY = os.getenv("SUPABASE_SERVICE_ROLE_KEY", "").strip()


def _headers() -> dict[str, str]:
    return {"apikey": SUPABASE_KEY, "Authorization": f"Bearer {SUPABASE_KEY}",
            "Content-Type": "application/json", "Prefer": "return=minimal"}


def _db(method: str, table: str, *, params: dict[str, str] | None = None, body: Any = None) -> Any:
    if not SUPABASE_URL or not SUPABASE_KEY:
        raise RuntimeError("Supabase service-role connection is required for durable autopilot activity")
    with httpx.Client(timeout=15.0) as client:
        response = client.request(method, f"{SUPABASE_URL}/rest/v1/{table}",
                                  params=params, json=body, headers=_headers())
        response.raise_for_status()
        if response.content:
            return response.json()
        return None


def _event(run_id: str, stage: str, message: str, *, agent_id: str | None = None,
           status: str = "running", payload: dict[str, Any] | None = None) -> None:
    _db("POST", "autopilot_events", body={
        "run_id": run_id, "event_type": "agent_activity", "stage": stage,
        "agent_id": agent_id, "status": status, "message": message[:2000],
        "payload": payload or {},
    })
    _db("PATCH", "autopilot_runs", params={"id": f"eq.{run_id}"},
        body={"status": status, "updated_at": datetime.now(timezone.utc).isoformat(),
              "heartbeat_at": datetime.now(timezone.utc).isoformat()})


def _save_message(conversation_id: str, run_id: str, role: str, content: str) -> None:
    _db("POST", "autopilot_messages", body={
        "conversation_id": conversation_id, "run_id": run_id, "role": role, "content": content[:30000],
    })


def _provider() -> tuple[str, str, str]:
    base = (os.getenv("AUTOPILOT_MODEL_BASE_URL") or os.getenv("AGENT_MODEL_BASE_URL")
            or os.getenv("AI_BASE_URL") or os.getenv("GROQ_BASE_URL")
            or "https://api.groq.com/openai/v1").strip().rstrip("/")
    key = (os.getenv("AUTOPILOT_MODEL_API_KEY") or os.getenv("AGENT_MODEL_API_KEY")
           or os.getenv("AI_API_KEY") or os.getenv("GROQ_API_KEY") or "").strip()
    model = (os.getenv("AUTOPILOT_DEFAULT_MODEL") or os.getenv("AGENT_DEFAULT_MODEL")
             or os.getenv("AI_DEFAULT_MODEL") or os.getenv("GROQ_DEFAULT_MODEL") or "").strip()
    if not key or not model:
        raise RuntimeError("Configure AUTOPILOT_MODEL_API_KEY and AUTOPILOT_DEFAULT_MODEL (or AI/Groq equivalents)")
    if not base.startswith("https://"):
        raise RuntimeError("AI provider endpoint must use HTTPS")
    return base, key, model


def _call_model(system: str, user: str, *, max_tokens: int = 2400) -> str:
    base, key, model = _provider()
    endpoint = base if base.endswith("/chat/completions") else f"{base}/chat/completions"
    with httpx.Client(timeout=httpx.Timeout(100, connect=10), follow_redirects=False) as client:
        response = client.post(endpoint, headers={"Authorization": f"Bearer {key}"},
            json={"model": model, "temperature": 0.35, "max_tokens": max_tokens,
                  "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}]})
        response.raise_for_status()
        data = response.json()
    choices = data.get("choices") or []
    if not choices:
        raise RuntimeError("Model provider returned no choices")
    return str((choices[0].get("message") or {}).get("content") or "").strip()


def _is_creator_request(message: str) -> bool:
    terms = ("youtube", "video", "shorts", "short ", "channel", "niche", "script", "upload",
             "viral", "content", "thumbnail", "daily videos", "rozana")
    low = message.casefold()
    return any(term in low for term in terms)


def _run_specialist(run_id: str, role_id: str, role_name: str, mission: str, user_message: str) -> dict[str, Any]:
    _event(run_id, "agent_started", f"{role_name} kaam shuru kar raha hai", agent_id=role_id)
    output = _call_model(
        "You are a specialist agent in a multi-agent YouTube production backend. "
        "Return practical, original work. Do not claim you browsed the live web or used tools unless the input contains evidence. "
        "Never invent research metrics, keyword volumes, competitor statistics, or citations. "
        "If live evidence is missing, clearly label assumptions and specify what tool is needed. "
        "Do not publish, spend money, or modify external accounts.",
        f"Role: {role_name}\nMission: {mission}\nUser request: {user_message}\n"
        "Return a concise, structured deliverable with actionable details.",
        max_tokens=2600,
    )
    _event(run_id, "agent_completed", f"{role_name} ne apna deliverable complete kar diya",
           agent_id=role_id, status="running", payload={"output_preview": output[:500]})
    return {"agent_id": role_id, "name": role_name, "output": output}


@celery_app.task(bind=True, name="autopilot_worker.run_chat", acks_late=True)
def run_chat(self, payload: dict[str, Any]) -> dict[str, Any]:
    run_id = str(payload["task_id"])
    conversation_id = str(payload["conversation_id"])
    message = str(payload["message"]).strip()
    try:
        _event(run_id, "understanding", "JARVIS request samajh raha hai", status="running")
        _save_message(conversation_id, run_id, "user", message)
        if not _is_creator_request(message):
            answer = _call_model(
                "You are JARVIS, the user's private AI operations assistant. Be concise, helpful and honest. "
                "Do not claim actions were completed unless tools actually executed them.",
                message, max_tokens=1800)
            _save_message(conversation_id, run_id, "assistant", answer)
            _db("PATCH", "autopilot_runs", params={"id": f"eq.{run_id}"},
                body={"status": "completed", "result": {"answer": answer},
                      "updated_at": datetime.now(timezone.utc).isoformat()})
            _event(run_id, "completed", "Jawab tayyar hai", status="completed")
            return {"status": "completed", "answer": answer}

        _event(run_id, "fleet_dispatch", "YouTube specialist fleet assign ho rahi hai", status="running")
        fleet = json.loads(FLEET_PATH.read_text(encoding="utf-8"))
        role_map = {r["id"]: r for r in fleet["roles"]}
        selected = [
            ("research-specialist", "Research & Trend Agent"),
            ("script-specialist", "Scriptwriting Agent"),
            ("seo-specialist", "SEO & Packaging Agent"),
            ("visual-production-specialist", "Visual Storyboard Agent"),
            ("publishing-reviewer", "Quality & Policy Reviewer"),
        ]
        max_parallel = max(1, min(int(os.getenv("AUTOPILOT_MAX_PARALLEL_AGENTS", "5")), 20))
        selected = selected[:max_parallel]
        _event(run_id, "fleet_assigned",
               f"{len(selected)} specialist agents assign huay; {fleet['agent_slots']} role slots available hain",
               status="running", payload={"agent_slots": fleet["agent_slots"], "active_agents": len(selected),
                                          "max_parallel": max_parallel})
        _event(run_id, "content_planning", "Content brief aur specialist tasks prepare ho rahe hain", status="running")

        results = []
        with concurrent.futures.ThreadPoolExecutor(max_workers=max_parallel) as pool:
            futures = [pool.submit(_run_specialist, run_id, role_id, role_name,
                                   role_map[role_id]["mission"], message)
                       for role_id, role_name in selected]
            for future in concurrent.futures.as_completed(futures):
                results.append(future.result())

        _event(run_id, "quality_review", "Quality reviewer aur orchestrator deliverables merge kar rahe hain", status="running")
        merged_input = json.dumps(results, ensure_ascii=False)[:24000]
        final = _call_model(
            "You are the chief YouTube production director. Combine the specialist deliverables into one useful answer. "
            "Return a polished production brief: niche/topic, script or outline if requested, title ideas, description, tags, "
            "visual shot list, Pexels search terms, caption/localization plan, quality risks, and next executable steps. "
            "Never invent live trend metrics or claim media was downloaded/rendered/published. "
            "Clearly separate completed AI-generated deliverables from pending external integrations.",
            f"User request:\n{message}\n\nSpecialist deliverables:\n{merged_input}",
            max_tokens=4500,
        )
        result = {
            "answer": final,
            "specialists": [{"agent_id": x["agent_id"], "name": x["name"]} for x in results],
            "agent_slots_available": fleet["agent_slots"],
            "execution_note": "AI content planning and specialist deliverables completed. Actual footage download, voice rendering, video rendering, and publishing require configured media/voice/YouTube workers.",
        }
        _save_message(conversation_id, run_id, "assistant", final)
        _db("PATCH", "autopilot_runs", params={"id": f"eq.{run_id}"},
            body={"status": "completed", "result": result,
                  "updated_at": datetime.now(timezone.utc).isoformat(),
                  "heartbeat_at": datetime.now(timezone.utc).isoformat()})
        _event(run_id, "completed", "Specialist team ka result ready hai", status="completed",
               payload={"specialists_completed": len(results), "agent_slots_available": fleet["agent_slots"]})
        return {"status": "completed", **result}
    except Exception as exc:
        safe_error = f"{type(exc).__name__}: {str(exc)[:600]}"
        _db("PATCH", "autopilot_runs", params={"id": f"eq.{run_id}"},
            body={"status": "failed", "error_message": safe_error,
                  "updated_at": datetime.now(timezone.utc).isoformat()})
        _event(run_id, "failed", "Task ruk gaya: " + safe_error, status="failed")
        raise
