"""Talking-avatar planning, with consent enforced in code.

Three legitimate paths exist, and this module tells you which one you are on:

1. **self**      — your own face and your own voice, with a consent record.
2. **licensed**  — a face/voice you have written permission to use.
3. **synthetic** — a generated persona. No real person is copied, so nothing
                   needs consent beyond your own ownership of the character.

What this module deliberately does **not** do is take a real person's name and
harvest their photos and voice from the internet to build a talking likeness.
That is impersonation, it is the exact failure mode that gets accounts banned and
creators sued, and no amount of "but it looks cool" changes the law. If you want
a named presenter, upload that person's own media with their written consent, or
use a synthetic persona.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

ALLOWED_RELATIONS = {"self", "licensed", "synthetic"}
MIN_VOICE_SAMPLE_SECONDS = 20
MAX_VOICE_SAMPLE_SECONDS = 300


@dataclass(slots=True)
class AvatarSpec:
    name: str = ""
    relation: str = "self"
    consent_confirmed: bool = False
    consent_record_id: str = ""
    image_path: str = ""
    voice_sample_path: str = ""
    public_figure: bool = False
    notes: list[str] = field(default_factory=list)

    @classmethod
    def from_dict(cls, data: dict[str, Any] | None) -> "AvatarSpec | None":
        if not data:
            return None
        return cls(
            name=str(data.get("name") or "").strip()[:80],
            relation=str(data.get("relation") or "self").strip().lower(),
            consent_confirmed=bool(data.get("consent_confirmed")),
            consent_record_id=str(data.get("consent_record_id") or "").strip()[:300],
            image_path=str(data.get("image_path") or "").strip(),
            voice_sample_path=str(data.get("voice_sample_path") or "").strip(),
            public_figure=bool(data.get("public_figure")),
        )


def evaluate(spec: AvatarSpec | None) -> dict[str, Any]:
    """Decide whether this avatar can be produced, and say why if not."""
    if spec is None:
        return {"requested": False, "status": "not_requested"}

    result: dict[str, Any] = {
        "requested": True,
        "name": spec.name or "(unnamed persona)",
        "relation": spec.relation,
        "status": "ready",
        "blocked": [],
        "needs": [],
        "steps": [],
        "policy": (
            "A real person's face or voice is only used with a consent record. "
            "Named public figures are refused outright."
        ),
    }

    if spec.relation not in ALLOWED_RELATIONS:
        result["blocked"].append(
            f"relation must be one of {sorted(ALLOWED_RELATIONS)}; got {spec.relation!r}"
        )

    if spec.public_figure:
        result["blocked"].append(
            "Refused: this is a real public figure. A synthesised likeness of a public figure "
            "is impersonation regardless of consent, and will not be produced."
        )

    if spec.relation in {"self", "licensed"}:
        if not (spec.consent_confirmed and spec.consent_record_id):
            result["blocked"].append(
                "A consent record is required. Upload the signed permission to your storage and "
                "pass consent_record_id with consent_confirmed=true."
            )

    if result["blocked"]:
        result["status"] = "blocked"
        return result

    if spec.relation == "synthetic":
        result["steps"] = [
            "Generate a face for the persona (media worker image task or an avatar provider).",
            "Pick a synthetic voice from the voice worker's TTS engines.",
            "Lip-sync the generated face to the narration.",
            "Composite the avatar over the scene during assembly.",
        ]
        result["needs"] = ["MEDIA_WORKER_URL", "VOICE_WORKER_URL"]
        if not spec.image_path:
            result["notes"] = ["No image supplied — one will be generated from the persona name."]
        return result

    # self / licensed with consent
    if not spec.image_path:
        result["needs"].append("image_path (a clear frontal photo of the speaker)")
    if not spec.voice_sample_path:
        result["needs"].append(
            f"voice_sample_path ({MIN_VOICE_SAMPLE_SECONDS}-{MAX_VOICE_SAMPLE_SECONDS}s of clean speech)"
        )
    result["needs"].extend(["MEDIA_WORKER_URL", "VOICE_WORKER_URL"])

    if result["needs"]:
        result["status"] = "needs_assets"
        result["steps"] = [
            "POST the photo to the voice worker asset store.",
            "POST the voice sample to /v1/voice/clone with the same consent record.",
            "Render narration with the cloned voice profile.",
            "Send narration audio + avatar photo to the media worker's lip_sync task.",
            "Composite the talking head over the timeline during assembly.",
        ]
        return result

    result["steps"] = [
        "Clone the voice from the supplied sample (consent record attached).",
        "Render narration with that voice profile.",
        "Lip-sync the supplied photo to the narration via the media worker.",
        "Composite the talking head into the timeline.",
    ]
    return result


def narration_plan(spec: AvatarSpec, beats: list[str]) -> list[dict[str, str]]:
    """Which line the avatar speaks, in order — used when wiring lip-sync jobs."""
    return [{"scene": str(index), "line": beat} for index, beat in enumerate(beats) if beat.strip()]
