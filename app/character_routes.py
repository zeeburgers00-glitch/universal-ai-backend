"""HTTP routes for the inner layers: character and mood.

`/v1/character` — who it is (presets, traits, language).
`/v1/affect` — how it currently sounds (a five-number mood vector with decay).
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from . import affect, character
from .security import require_api_key

router = APIRouter(tags=["character"], dependencies=[Depends(require_api_key)])


class CharacterUpdate(BaseModel):
    name: str | None = Field(default=None, max_length=40)
    address: str | None = Field(default=None, max_length=24)
    language: str | None = Field(default=None, pattern="^(auto|en|hi|ur)$")
    traits: dict[str, float] | None = None
    tone_rules: list[str] | None = None


class PresetRequest(BaseModel):
    preset: str = Field(description="jarvis | mentor | friend | analyst")
    name: str | None = Field(default=None, max_length=40)


class AffectRequest(BaseModel):
    event: str = Field(description="praise, thanks, insult, frustration, success, failure, ...")
    weight: float = Field(default=1.0, ge=0.0, le=3.0)
    note: str = Field(default="", max_length=200)


@router.get("/v1/character")
def get_character() -> dict[str, Any]:
    return {"character": character.load(), "prompt_block": character.prompt_block()}


@router.get("/v1/character/presets")
def character_presets() -> dict[str, Any]:
    return character.presets()


@router.put("/v1/character")
def put_character(body: CharacterUpdate) -> dict[str, Any]:
    updated = character.update(name=body.name, address=body.address, language=body.language,
                               traits=body.traits, tone_rules=body.tone_rules)
    return {"character": updated, "prompt_block": character.prompt_block(updated)}


@router.post("/v1/character/preset")
def set_preset(body: PresetRequest) -> dict[str, Any]:
    try:
        updated = character.apply_preset(body.preset, body.name)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return {"character": updated, "prompt_block": character.prompt_block(updated)}


@router.get("/v1/affect")
def get_affect() -> dict[str, Any]:
    return affect.state()


@router.post("/v1/affect/touch")
def touch_affect(body: AffectRequest) -> dict[str, Any]:
    try:
        moved = affect.touch(body.event, note=body.note, weight=body.weight)
    except affect.AffectError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return {"moved": moved, "state": affect.state()}


@router.post("/v1/affect/reset")
def reset_affect() -> dict[str, Any]:
    return affect.reset()
