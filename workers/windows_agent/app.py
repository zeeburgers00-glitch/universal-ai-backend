import base64
import io
import json
import os
import secrets
import subprocess
import webbrowser
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from fastapi import Depends, FastAPI, Header, HTTPException
from pydantic import BaseModel, Field

app = FastAPI(title="Universal AI Windows Agent", version="0.1.0")
WORKSPACE = Path(os.getenv("WINDOWS_AGENT_WORKSPACE", str(Path.home() / "UniversalAIAgentWorkspace"))).resolve()
WORKSPACE.mkdir(parents=True, exist_ok=True)


def require_agent_key(authorization: str | None = Header(default=None)) -> bool:
    expected = os.getenv("DESKTOP_AGENT_API_KEY", "").strip()
    if not expected:
        raise HTTPException(status_code=503, detail="DESKTOP_AGENT_API_KEY is not configured")
    received = authorization.removeprefix("Bearer ").strip() if authorization else ""
    if not received or not secrets.compare_digest(received, expected):
        raise HTTPException(status_code=401, detail="Invalid desktop agent credentials")
    return True


class DesktopAction(BaseModel):
    task_id: str | None = Field(default=None, max_length=120, pattern=r"^[A-Za-z0-9_-]+$")
    paired_device_id: str = Field(min_length=3, max_length=300)
    action: str = Field(min_length=3, max_length=80, pattern=r"^[a-zA-Z0-9_-]+$")
    parameters: dict[str, Any] = Field(default_factory=dict)
    user_approved: bool = False


def _require_windows() -> None:
    if os.name != "nt":
        raise HTTPException(status_code=503, detail="The desktop agent must run on the user's Windows PC")


def _inside_workspace(relative_path: str) -> Path:
    if not relative_path or Path(relative_path).is_absolute():
        raise HTTPException(status_code=400, detail="Provide a relative workspace path")
    target = (WORKSPACE / relative_path).resolve()
    if target != WORKSPACE and WORKSPACE not in target.parents:
        raise HTTPException(status_code=403, detail="Path escapes the configured agent workspace")
    return target


def _app_allowlist() -> dict[str, list[str]]:
    raw = os.getenv("WINDOWS_AGENT_APPS_JSON", "").strip()
    if raw:
        try:
            value = json.loads(raw)
            if not isinstance(value, dict):
                raise ValueError("app allowlist must be a JSON object")
            return {str(k).lower(): [str(part) for part in v] for k, v in value.items() if isinstance(v, list) and v}
        except (json.JSONDecodeError, ValueError) as exc:
            raise HTTPException(status_code=500, detail="WINDOWS_AGENT_APPS_JSON is invalid") from exc
    return {
        "notepad": ["notepad.exe"],
        "calculator": ["calc.exe"],
        "explorer": ["explorer.exe"],
        "edge": ["msedge.exe"],
        "chrome": ["chrome.exe"],
    }


def _require_approval(req: DesktopAction, message: str = "This desktop action requires explicit approval") -> None:
    if not req.user_approved:
        raise HTTPException(status_code=409, detail=message)


@app.get("/health")
def health():
    return {
        "status": "ok",
        "service": "windows-desktop-agent",
        "windows_host": os.name == "nt",
        "workspace_configured": str(WORKSPACE),
        "workspace_only_file_access": True,
        "arbitrary_shell_enabled": False,
    }


@app.post("/v1/desktop/actions", dependencies=[Depends(require_agent_key)])
def desktop_action(req: DesktopAction):
    _require_windows()
    if not req.paired_device_id or req.paired_device_id != os.getenv("WINDOWS_AGENT_DEVICE_ID", "").strip():
        raise HTTPException(status_code=403, detail="Paired device ID does not match this Windows agent")
    action = req.action
    params = req.parameters

    if action == "get_status":
        import platform
        return {
            "status": "ok",
            "device_id": os.getenv("WINDOWS_AGENT_DEVICE_ID"),
            "hostname": os.getenv("COMPUTERNAME", ""),
            "platform": platform.platform(),
            "python_version": platform.python_version(),
            "workspace": str(WORKSPACE),
            "allowed_apps": sorted(_app_allowlist().keys()),
        }

    if action == "open_app":
        name = str(params.get("app_name", "")).lower()
        command = _app_allowlist().get(name)
        if not command:
            raise HTTPException(status_code=403, detail="App is not in WINDOWS_AGENT_APPS_JSON allowlist")
        subprocess.Popen(command, shell=False, cwd=str(WORKSPACE))
        return {"status": "started", "app_name": name}

    if action == "open_url":
        _require_approval(req, "Opening a URL requires explicit approval")
        url = str(params.get("url", "")).strip()
        parsed = urlparse(url)
        if parsed.scheme != "https" or not parsed.hostname:
            raise HTTPException(status_code=400, detail="Only HTTPS URLs are allowed")
        allowed = {x.strip().lower() for x in os.getenv("WINDOWS_AGENT_ALLOWED_URL_HOSTS", "").split(",") if x.strip()}
        if not allowed or parsed.hostname.lower() not in allowed:
            raise HTTPException(status_code=403, detail="URL host is not in WINDOWS_AGENT_ALLOWED_URL_HOSTS")
        webbrowser.open(url, new=2)
        return {"status": "opened", "host": parsed.hostname}

    if action in {"capture_screen", "screenshot"}:
        import pyautogui
        image = pyautogui.screenshot()
        buf = io.BytesIO()
        image.save(buf, format="PNG")
        return {"status": "captured", "mime_type": "image/png", "image_base64": base64.b64encode(buf.getvalue()).decode("ascii")}

    if action == "type_text":
        _require_approval(req, "Typing into the currently focused window requires explicit approval")
        text = str(params.get("text", ""))
        if not text or len(text) > 2000:
            raise HTTPException(status_code=400, detail="text must contain 1-2000 characters")
        try:
            import pyautogui
            import pyperclip
            pyperclip.copy(text)
            pyautogui.hotkey("ctrl", "v")
        except Exception as exc:
            raise HTTPException(status_code=500, detail=f"Typing failed: {type(exc).__name__}") from exc
        return {"status": "typed", "characters": len(text)}

    if action == "click":
        _require_approval(req, "Mouse clicks require explicit approval")
        x, y = params.get("x"), params.get("y")
        if not isinstance(x, int) or not isinstance(y, int) or abs(x) > 100000 or abs(y) > 100000:
            raise HTTPException(status_code=400, detail="x and y must be integer screen coordinates")
        button = str(params.get("button", "left"))
        if button not in {"left", "right", "middle"}:
            raise HTTPException(status_code=400, detail="Invalid mouse button")
        import pyautogui
        width, height = pyautogui.size()
        if not (0 <= x < width and 0 <= y < height):
            raise HTTPException(status_code=400, detail="Coordinates must be on-screen")
        pyautogui.click(x=x, y=y, button=button)
        return {"status": "clicked", "x": x, "y": y, "button": button}

    if action == "read_file":
        target = _inside_workspace(str(params.get("path", "")))
        if not target.is_file():
            raise HTTPException(status_code=404, detail="Workspace file not found")
        if target.stat().st_size > 200_000:
            raise HTTPException(status_code=413, detail="File is larger than the 200 KB text-read limit")
        try:
            text = target.read_text(encoding="utf-8")
        except UnicodeDecodeError as exc:
            raise HTTPException(status_code=415, detail="Only UTF-8 text files are supported by read_file") from exc
        return {"status": "read", "path": str(target.relative_to(WORKSPACE)), "content": text}

    if action == "write_file":
        _require_approval(req, "Writing files requires explicit approval")
        target = _inside_workspace(str(params.get("path", "")))
        content = params.get("content")
        if not isinstance(content, str) or len(content.encode("utf-8")) > 200_000:
            raise HTTPException(status_code=400, detail="content must be UTF-8 text up to 200 KB")
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")
        return {"status": "written", "path": str(target.relative_to(WORKSPACE)), "bytes": len(content.encode("utf-8"))}

    if action == "delete_file":
        _require_approval(req, "Deleting files requires explicit approval")
        target = _inside_workspace(str(params.get("path", "")))
        if not target.is_file():
            raise HTTPException(status_code=404, detail="Workspace file not found")
        target.unlink()
        return {"status": "deleted", "path": str(target.relative_to(WORKSPACE))}

    if action == "shutdown":
        _require_approval(req, "Shutting down Windows needs explicit approval")
        if os.getenv("WINDOWS_AGENT_ALLOW_SHUTDOWN", "").lower() != "true":
            raise HTTPException(status_code=403, detail="Shutdown is disabled by local policy")
        subprocess.Popen(["shutdown.exe", "/s", "/t", "30"], shell=False, cwd=str(WORKSPACE))
        return {"status": "shutdown_scheduled", "delay_seconds": 30}

    if action in {"install_software", "run_approved_script", "change_system_setting", "send_message"}:
        raise HTTPException(status_code=501, detail="This action is intentionally disabled in the initial Windows agent; use a reviewed, narrowly allowlisted plugin")

    raise HTTPException(status_code=400, detail="Unsupported desktop action")
