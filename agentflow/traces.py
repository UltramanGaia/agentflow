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
class CodexTraceParser(BaseTraceParser):
    def supports_raw_stdout_fallback(self) -> bool:
        return False

    def _is_ignorable_item_warning(self, item: dict[str, Any]) -> bool:
        item_type = item.get("type") or item.get("details", {}).get("type")
        if item_type != "error":
            return False
        message = str(item.get("message") or "")
        return message.startswith("Under-development features enabled:")

    def feed(self, line: str) -> list[NormalizedTraceEvent]:
        payload = _json(line)
        if payload is None:
            text = line.rstrip()
            self.remember(text)
            return [self.emit("stdout", "stdout", text, line)] if text else []

        event_type = payload.get("type") or payload.get("method") or payload.get("event") or "codex"
        events: list[NormalizedTraceEvent] = []

        if event_type in {"response.output_text.delta", "agent_message_delta", "item/agentMessage/delta"}:
            text = _stringify(payload.get("delta") or payload.get("params") or payload)
            self.remember(text)
            events.append(self.emit("assistant_delta", "Assistant delta", text, payload))
        elif event_type == "response.output_item.done":
            item = payload.get("item", {})
            item_type = item.get("type")
            if item_type == "message":
                text = _stringify(item.get("content"))
                self.remember(text)
                events.append(self.emit("assistant_message", "Assistant message", text, payload))
            elif item_type == "function_call":
                events.append(self.emit("tool_call", f"Tool call: {item.get('name', 'tool')}", _stringify(item.get("arguments")), payload))
            else:
                events.append(self.emit("event", str(event_type), _stringify(payload), payload))
        elif event_type in {"item.completed", "item/completed"}:
            item = payload.get("item") or payload.get("params", {}).get("item") or {}
            if self._is_ignorable_item_warning(item):
                return []
            text = _stringify(item)
            item_type = item.get("type") or item.get("details", {}).get("type") or "item"
            if item_type in {"agentMessage", "agent_message"} and text:
                self.remember(text)
            events.append(self.emit("item_completed", f"Item completed: {item_type}", text, payload))
        elif event_type in {"item.started", "item/started"}:
            item = payload.get("item") or payload.get("params", {}).get("item") or {}
            item_type = item.get("type") or item.get("details", {}).get("type") or "item"
            events.append(self.emit("item_started", f"Item started: {item_type}", _stringify(item), payload))
        elif event_type in {"response.completed", "turn/completed", "turn.completed"}:
            text = _stringify(payload.get("response") or payload.get("params") or payload)
            if text:
                self.remember(text)
            events.append(self.emit("completed", "Turn completed", text, payload))
        elif event_type in {"command/exec/outputDelta", "item/commandExecution/outputDelta"}:
            text = _stringify(payload.get("params") or payload)
            events.append(self.emit("command_output", "Command output", text, payload))
        else:
            events.append(self.emit("event", str(event_type), _stringify(payload), payload))
        return events


@dataclass(slots=True)
class ClaudeTraceParser(BaseTraceParser):
    def supports_raw_stdout_fallback(self) -> bool:
        return False

    def feed(self, line: str) -> list[NormalizedTraceEvent]:
        payload = _json(line)
        if payload is None:
            text = line.rstrip()
            self.remember(text)
            return [self.emit("stdout", "stdout", text, line)] if text else []

        event_type = payload.get("type") or "claude"
        if event_type == "system":
            subtype = str(payload.get("subtype") or "")
            if subtype.startswith("hook_"):
                if subtype in {"hook_error", "hook_failed"}:
                    content = _stringify(payload.get("error") or payload.get("stderr") or payload.get("output"))
                    title = f"Hook failed: {payload.get('hook_name', 'hook')}"
                    return [self.emit("hook_error", title, content, payload)]
                return []
        text = _stringify(payload.get("message") or payload.get("result") or payload.get("delta") or payload.get("content"))
        events: list[NormalizedTraceEvent] = []

        if event_type in {"assistant", "message"}:
            self.remember(text)
            events.append(self.emit("assistant_message", "Assistant message", text, payload))
        elif event_type in {"result", "final"}:
            if text and text != self.last_message:
                self.remember(text)
            events.append(self.emit("result", "Result", text, payload))
        elif event_type in {"tool_use", "tool_result"}:
            title = f"{event_type.replace('_', ' ').title()}"
            events.append(self.emit(event_type, title, text, payload))
        else:
            events.append(self.emit("event", str(event_type), text, payload))
        return events


@dataclass(slots=True)
class PiTraceParser(BaseTraceParser):
    """Parser for Pi CLI's ``--mode json`` event stream.

    Pi emits ordered events per turn: ``session``, ``agent_start``, ``turn_start``,
    ``message_start``, ``message_update`` (with ``text_delta`` / ``text_end`` sub-events),
    ``message_end``, ``turn_end``, ``agent_end``. The assistant text for the final
    turn is the authoritative output; we extract it from ``message_end`` and
    ``agent_end`` events, which carry the complete assembled content.
    """

    def supports_raw_stdout_fallback(self) -> bool:
        return False

    def _extract_text_from_content(self, content: Any) -> str:
        if isinstance(content, list):
            parts: list[str] = []
            for item in content:
                if isinstance(item, dict) and item.get("type") == "text":
                    text = item.get("text")
                    if isinstance(text, str):
                        parts.append(text)
            return "".join(parts)
        if isinstance(content, str):
            return content
        return ""

    def feed(self, line: str) -> list[NormalizedTraceEvent]:
        payload = _json(line)
        if payload is None:
            text = line.rstrip()
            self.remember(text)
            return [self.emit("stdout", "stdout", text, line)] if text else []

        event_type = payload.get("type") or "pi"
        events: list[NormalizedTraceEvent] = []

        if event_type == "message_end":
            message = payload.get("message") or {}
            if message.get("role") == "assistant":
                text = self._extract_text_from_content(message.get("content"))
                if text:
                    self.remember(text)
                events.append(self.emit("assistant_message", "Assistant message", text, payload))
            return events

        if event_type == "agent_end":
            messages = payload.get("messages") or []
            final_text: str | None = None
            for message in messages:
                if isinstance(message, dict) and message.get("role") == "assistant":
                    text = self._extract_text_from_content(message.get("content"))
                    if text:
                        final_text = text
            if final_text and final_text != self.last_message:
                self.remember(final_text)
            events.append(self.emit("agent_end", "Agent end", final_text or "", payload))
            return events

        if event_type == "message_update":
            inner = payload.get("assistantMessageEvent") or {}
            sub_type = inner.get("type")
            if sub_type == "text_delta":
                delta = inner.get("delta")
                if isinstance(delta, str):
                    events.append(self.emit("assistant_delta", "Assistant delta", delta, payload))
            elif sub_type == "text_end":
                content = inner.get("content")
                if isinstance(content, str):
                    events.append(self.emit("assistant_text", "Assistant text", content, payload))
            return events

        if event_type == "turn_end":
            message = payload.get("message") or {}
            text = self._extract_text_from_content(message.get("content"))
            events.append(self.emit("turn_end", "Turn end", text, payload))
            return events

        if event_type in {"session", "agent_start", "turn_start", "message_start"}:
            events.append(self.emit(event_type, event_type.replace("_", " ").title(), None, payload))
            return events

        events.append(self.emit("event", str(event_type), _stringify(payload), payload))
        return events


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
        case AgentKind.CODEX:
            return CodexTraceParser(node_id=node_id, agent=agent)
        case AgentKind.CLAUDE:
            return ClaudeTraceParser(node_id=node_id, agent=agent)
        case AgentKind.PI:
            return PiTraceParser(node_id=node_id, agent=agent)
        case AgentKind.GAIA:
            return GaiaTraceParser(node_id=node_id, agent=agent)
    return GenericTraceParser(node_id=node_id, agent=agent)
