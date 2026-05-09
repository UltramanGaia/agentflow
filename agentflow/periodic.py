from __future__ import annotations

import json

from pydantic import BaseModel, Field, ValidationError


class PeriodicAction(BaseModel):
    kind: str
    node_ids: list[str] = Field(default_factory=list)
    reason: str | None = None


class PeriodicActionEnvelope(BaseModel):
    analysis: str | None = None
    actions: list[PeriodicAction] = Field(default_factory=list)


def normalize_periodic_output_text(text: str | None) -> str:
    normalized = str(text or "").strip()
    if normalized.startswith("```"):
        lines = normalized.splitlines()
        if len(lines) >= 3 and lines[-1].strip() == "```":
            normalized = "\n".join(lines[1:-1]).strip()
            if normalized.lower().startswith("json\n"):
                normalized = normalized[5:].strip()
    return normalized


def parse_periodic_actions(text: str | None) -> tuple[PeriodicActionEnvelope | None, str | None]:
    normalized = normalize_periodic_output_text(text)
    if not normalized:
        return PeriodicActionEnvelope(), None
    try:
        payload = json.loads(normalized)
    except json.JSONDecodeError as exc:
        return None, f"invalid JSON control envelope: {exc}"
    try:
        return PeriodicActionEnvelope.model_validate(payload), None
    except ValidationError as exc:  # pragma: no cover - pydantic error details vary
        return None, f"invalid control envelope: {exc}"
