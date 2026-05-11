from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any

from agentflow.specs_core import AgentKind
from agentflow.specs_models import NormalizedTraceEvent


def _json(line: str) -> Any | None:
    line = line.strip()
    if not line:
        return None
    try:
        return json.loads(line)
    except json.JSONDecodeError:
        return None


def _stringify(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    if isinstance(value, (int, float, bool)):
        return str(value)
    if isinstance(value, list):
        return "\n".join(part for item in value if (part := _stringify(item)))
    if isinstance(value, dict):
        parts: list[str] = []
        for key in ("text", "delta", "content", "output", "result", "message", "arguments_part"):
            if key in value:
                text = _stringify(value[key])
                if text:
                    parts.append(text)
        if parts:
            return "\n".join(parts)
    return ""


@dataclass(slots=True)
class BaseTraceParser:
    node_id: str
    agent: AgentKind
    attempt: int = 1
    final_chunks: list[str] = field(default_factory=list)
    last_message: str | None = None

    def emit(self, kind: str, title: str, content: str | None = None, raw: Any | None = None, source: str = "stdout") -> NormalizedTraceEvent:
        return NormalizedTraceEvent(
            node_id=self.node_id,
            agent=self.agent,
            attempt=self.attempt,
            source=source,
            kind=kind,
            title=title,
            content=content,
            raw=raw,
        )

    def start_attempt(self, attempt: int) -> None:
        self.attempt = attempt
        self.final_chunks.clear()
        self.last_message = None

    def remember(self, text: str | None) -> None:
        if text:
            self.final_chunks.append(text)
            self.last_message = text

    def feed(self, line: str) -> list[NormalizedTraceEvent]:
        raise NotImplementedError

    def finalize(self) -> str:
        joined = "\n".join(chunk.strip() for chunk in self.final_chunks if chunk and chunk.strip()).strip()
        return joined or (self.last_message or "")

    def supports_raw_stdout_fallback(self) -> bool:
        return True


@dataclass(slots=True)
class GaiaTraceParser(BaseTraceParser):
    def feed(self, line: str) -> list[NormalizedTraceEvent]:
        payload = _json(line)
        if payload is None:
            text = line.rstrip()
            self.remember(text)
            return [self.emit("stdout", "stdout", text, line)] if text else []

        event_type = str(
            payload.get("type")
            or payload.get("event")
            or payload.get("role")
            or "gaia"
        )
        text = _stringify(
            payload.get("message")
            or payload.get("result")
            or payload.get("output")
            or payload.get("delta")
            or payload.get("content")
            or payload.get("text")
            or payload
        )
        events: list[NormalizedTraceEvent] = []

        if event_type in {"assistant", "message", "assistant_message"}:
            self.remember(text)
            events.append(self.emit("assistant_message", "Assistant message", text, payload))
        elif event_type in {"result", "final", "completed", "done"}:
            if text and text != self.last_message:
                self.remember(text)
            events.append(self.emit("result", "Result", text, payload))
        elif event_type in {"tool_use", "tool_call", "tool_result"}:
            title = event_type.replace("_", " ").title()
            events.append(self.emit(event_type, title, text, payload))
        else:
            if text:
                self.remember(text)
            events.append(self.emit("event", event_type, text, payload))
        return events


@dataclass(slots=True)
class GenericTraceParser(BaseTraceParser):
    def feed(self, line: str) -> list[NormalizedTraceEvent]:
        text = line.rstrip()
        self.remember(text)
        return [self.emit("stdout", "stdout", text, line)] if text else []


def create_trace_parser(agent: AgentKind, node_id: str) -> BaseTraceParser:
    match agent:
        case AgentKind.GAIA:
            return GaiaTraceParser(node_id=node_id, agent=agent)
    return GenericTraceParser(node_id=node_id, agent=agent)
