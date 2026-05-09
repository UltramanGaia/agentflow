from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field

from agentflow.specs_models import NormalizedTraceEvent


class NodeRuntimeState(BaseModel):
    """Ephemeral per-node execution state kept in memory only."""

    model_config = ConfigDict(extra="forbid")

    stdout_lines: list[str] = Field(default_factory=list)
    stderr_lines: list[str] = Field(default_factory=list)
    trace_events: list[NormalizedTraceEvent] = Field(default_factory=list)
    current_attempt: int = 0
    last_tick_started_at: str | None = None
    next_scheduled_at: str | None = None
