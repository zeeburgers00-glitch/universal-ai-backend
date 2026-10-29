import os
import secrets
from typing import Any

import httpx
from fastapi import Depends, FastAPI, Header, HTTPException
from pydantic import BaseModel, Field

app = FastAPI(title="Universal AI Channel Worker", version="0.1.0")


def require_worker_key(authorization: str | None = Header(default=None)) -> bool:
    expected = os.getenv("CHANNEL_WORKER_API_KEY", "").strip()
    if not expected:
        raise HTTPException(status_code=503, detail="CHANNEL_WORKER_API_KEY is not configured")
    received = authorization.removeprefix("Bearer ").strip() if authorization else ""
    if not received or not secrets.compare_digest(received, expected):
        raise HTTPException(status_code=401, detail="Invalid worker credentials")
    return True


class ChannelAction(BaseModel):
    task_id: str = Field(min_length=8, max_length=120, pattern=r"^[A-Za-z0-9_-]+$")
    channel_id: str = Field(min_length=2, max_length=100, pattern=r"^[a-zA-Z0-9_-]+$")
    connection_id: str = Field(min_length=3, max_length=300)
    action: str = Field(min_length=3, max_length=80, pattern=r"^[a-zA-Z0-9_-]+$")
    target_id: str = Field(min_length=1, max_length=300)
    text: str = Field(default="", max_length=12000)
    title: str | None = Field(default=None, max_length=300)
    approved_template_name: str | None = Field(default=None, max_length=200)
    user_approved: bool = False


CONFIG = {
    "telegram": {"connection_env": "TELEGRAM_CONNECTION_ID", "token_env": "TELEGRAM_BOT_TOKEN"},
    "discord": {"connection_env": "DISCORD_CONNECTION_ID", "token_env": "DISCORD_BOT_TOKEN"},
    "slack": {"connection_env": "SLACK_CONNECTION_ID", "token_env": "SLACK_BOT_TOKEN"},
    "whatsapp-cloud": {"connection_env": "WHATSAPP_CONNECTION_ID", "token_env": "WHATSAPP_ACCESS_TOKEN"},
}


@app.get("/health")
def health():
    return {
        "status": "ok",
        "service": "channel-worker",
        "connectors": {
            key: {
                "configured": bool(os.getenv(value["connection_env"], "").strip() and os.getenv(value["token_env"], "").strip()),
                "connection_env": value["connection_env"],
                "token_configured": bool(os.getenv(value["token_env"], "").strip()),
            }
            for key, value in CONFIG.items()
        },
    }


def _validate_connection(channel: str, connection_id: str, target_id: str) -> str:
    config = CONFIG.get(channel)
    if not config:
        raise HTTPException(status_code=501, detail=f"{channel} connector is not implemented in this worker build")
    configured_id = os.getenv(config["connection_env"], "").strip()
    token = os.getenv(config["token_env"], "").strip()
    if not configured_id or not token:
        raise HTTPException(status_code=503, detail=f"{channel} connector is not configured")
    if connection_id != configured_id:
        raise HTTPException(status_code=403, detail="Channel connection ID is not configured for this worker")
    allowlist_env = {
        "telegram": "TELEGRAM_ALLOWED_TARGET_IDS",
        "discord": "DISCORD_ALLOWED_TARGET_IDS",
        "slack": "SLACK_ALLOWED_TARGET_IDS",
        "whatsapp-cloud": "WHATSAPP_ALLOWED_TARGET_IDS",
    }[channel]
    raw_allowed = os.getenv(allowlist_env, "").strip()
    allowed = {x.strip() for x in raw_allowed.split(",") if x.strip()}
    if not allowed or target_id not in allowed:
        raise HTTPException(status_code=403, detail=f"Target is not in the server-side {channel} allowlist")
    return token


async def _telegram(req: ChannelAction, token: str) -> dict[str, Any]:
    if req.action != "send_message" or not req.text.strip():
        raise HTTPException(status_code=400, detail="Telegram connector supports send_message with non-empty text")
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    async with httpx.AsyncClient(timeout=httpx.Timeout(20, connect=8), follow_redirects=False) as client:
        response = await client.post(url, json={"chat_id": req.target_id, "text": req.text[:12000]})
    if response.status_code >= 400:
        raise HTTPException(status_code=502, detail="Telegram API request failed")
    data = response.json()
    if not data.get("ok"):
        raise HTTPException(status_code=502, detail="Telegram API did not accept the message")
    return {"status": "sent", "platform": "telegram", "message_id": str(data.get("result", {}).get("message_id", ""))}


async def _discord(req: ChannelAction, token: str) -> dict[str, Any]:
    if req.action != "send_message" or not req.text.strip():
        raise HTTPException(status_code=400, detail="Discord connector supports send_message with non-empty text")
    if not req.target_id.isdigit():
        raise HTTPException(status_code=400, detail="Discord target channel ID must be numeric")
    async with httpx.AsyncClient(timeout=httpx.Timeout(20, connect=8), follow_redirects=False) as client:
        response = await client.post(
            f"https://discord.com/api/v10/channels/{req.target_id}/messages",
            json={"content": req.text[:2000]},
            headers={"Authorization": f"Bot {token}", "Content-Type": "application/json"},
        )
    if response.status_code >= 400:
        raise HTTPException(status_code=502, detail=f"Discord API rejected the message (HTTP {response.status_code})")
    data = response.json()
    return {"status": "sent", "platform": "discord", "message_id": str(data.get("id", ""))}


async def _slack(req: ChannelAction, token: str) -> dict[str, Any]:
    if req.action != "send_message" or not req.text.strip():
        raise HTTPException(status_code=400, detail="Slack connector supports send_message with non-empty text")
    async with httpx.AsyncClient(timeout=httpx.Timeout(20, connect=8), follow_redirects=False) as client:
        response = await client.post(
            "https://slack.com/api/chat.postMessage",
            json={"channel": req.target_id, "text": req.text[:12000]},
            headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json; charset=utf-8"},
        )
    if response.status_code >= 400:
        raise HTTPException(status_code=502, detail="Slack API request failed")
    data = response.json()
    if not data.get("ok"):
        raise HTTPException(status_code=502, detail=f"Slack API rejected the message: {data.get('error', 'unknown error')}")
    return {"status": "sent", "platform": "slack", "message_ts": data.get("ts"), "channel": data.get("channel")}


async def _whatsapp_template(req: ChannelAction, token: str) -> dict[str, Any]:
    if req.action != "send_template_message":
        raise HTTPException(status_code=400, detail="WhatsApp connector only supports approved template messages in this worker build")
    if not req.approved_template_name:
        raise HTTPException(status_code=400, detail="approved_template_name is required")
    phone_id = os.getenv("WHATSAPP_PHONE_NUMBER_ID", "").strip()
    api_version = os.getenv("META_GRAPH_API_VERSION", "").strip()
    if not phone_id or not api_version.startswith("v"):
        raise HTTPException(status_code=503, detail="Configure WHATSAPP_PHONE_NUMBER_ID and META_GRAPH_API_VERSION")
    payload = {
        "messaging_product": "whatsapp",
        "to": req.target_id,
        "type": "template",
        "template": {
            "name": req.approved_template_name,
            "language": {"code": os.getenv("WHATSAPP_TEMPLATE_LANGUAGE", "en_US")},
        },
    }
    async with httpx.AsyncClient(timeout=httpx.Timeout(20, connect=8), follow_redirects=False) as client:
        response = await client.post(
            f"https://graph.facebook.com/{api_version}/{phone_id}/messages",
            json=payload,
            headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
        )
    if response.status_code >= 400:
        raise HTTPException(status_code=502, detail="WhatsApp API request failed; verify template, opt-in, and account permissions")
    data = response.json()
    messages = data.get("messages") or []
    return {"status": "sent" if messages else "accepted", "platform": "whatsapp-cloud",
            "message_id": (messages[0].get("id") if messages else None)}


@app.post("/v1/channels/action", dependencies=[Depends(require_worker_key)])
async def run_channel_action(req: ChannelAction):
    if not req.user_approved:
        raise HTTPException(status_code=409, detail="External channel messages require explicit user approval")
    token = _validate_connection(req.channel_id, req.connection_id, req.target_id)
    if req.channel_id == "telegram":
        return await _telegram(req, token)
    if req.channel_id == "discord":
        return await _discord(req, token)
    if req.channel_id == "slack":
        return await _slack(req, token)
    if req.channel_id == "whatsapp-cloud":
        return await _whatsapp_template(req, token)
    raise HTTPException(status_code=501, detail=f"{req.channel_id} connector is cataloged but not implemented here")
