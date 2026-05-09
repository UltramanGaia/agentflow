from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from agentflow.provider import resolve_provider
from agentflow.specs_core import (
    AgentKind,
    CaptureMode,
    FanoutSpec,
    LocalTarget,
    NodeStatus,
    PeriodicScheduleSpec,
    ProviderConfig,
    RepoInstructionsMode,
    RunStatus,
    SkipCriterion,
    SuccessCriterion,
    TargetSpec,
    ToolAccess,
    _INTERACTIVE_AGENT_KINDS,
    builtin_agent_kind,
)


class NodeSpec(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    agent: AgentKind | str
    prompt: str
    depends_on: list[str] = Field(default_factory=list)
    on_failure_restart: list[str] = Field(default_factory=list)
    model: str | None = None
    provider: str | ProviderConfig | None = None
    tools: ToolAccess = ToolAccess.READ_ONLY
    skills: list[str] = Field(default_factory=list)
    target: TargetSpec = Field(default_factory=LocalTarget)
    capture: CaptureMode = CaptureMode.FINAL
    repo_instructions_mode: RepoInstructionsMode = RepoInstructionsMode.INHERIT
    output_key: str | None = None
    timeout_seconds: int | None = Field(default=1800, gt=0)
    env: dict[str, str] = Field(default_factory=dict)
    executable: str | None = None
    extra_args: list[str] = Field(default_factory=list)
    description: str | None = None
    skip_if: list[SkipCriterion] = Field(default_factory=list)
    success_criteria: list[SuccessCriterion] = Field(default_factory=list)
    retries: int = Field(default=0, ge=0)
    retry_backoff_seconds: float = Field(default=1.0, ge=0.0)
    retry_backoff_max_seconds: float = Field(default=300.0, ge=0.0)
    retry_backoff_strategy: Literal["linear", "exponential"] = "exponential"
    schedule: PeriodicScheduleSpec | None = None
    fanout_group: str | None = Field(default=None, exclude=True)
    fanout_member: dict[str, Any] | None = Field(default=None, exclude=True)
    fanout_dependencies: dict[str, list[str]] = Field(default_factory=dict, exclude=True)

    @field_validator("agent")
    @classmethod
    def validate_agent(cls, value: AgentKind | str) -> AgentKind | str:
        if isinstance(value, AgentKind):
            return value
        normalized = str(value).strip()
        if not normalized:
            raise ValueError("`agent` must not be empty")
        return builtin_agent_kind(normalized) or normalized

    @model_validator(mode="after")
    def ensure_unique_dependencies(self) -> "NodeSpec":
        self.depends_on = list(dict.fromkeys(self.depends_on))
        if self.schedule is not None:
            if self.fanout_group is not None:
                raise ValueError("scheduled nodes cannot also use `fanout`")
            if self.target.kind != "local":
                raise ValueError("scheduled nodes currently require a local target")
        resolve_provider(self.provider, self.agent)
        return self


class PipelineSpec(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str
    description: str | None = None
    working_dir: str = "."
    optimizer: str | None = None
    n_run: int = Field(default=1, ge=1)
    concurrency: int = Field(default=4, ge=1)
    fail_fast: bool = False
    max_iterations: int = Field(default=10, ge=1)
    scratchboard: bool = False
    use_worktree: bool = False
    node_defaults: dict[str, Any] | None = None
    agent_defaults: dict[AgentKind, dict[str, Any]] = Field(default_factory=dict)
    local_target_defaults: LocalTarget | None = None
    fanouts: dict[str, list[str]] = Field(default_factory=dict)
    nodes: list[NodeSpec]

    @model_validator(mode="after")
    def validate_nodes(self) -> "PipelineSpec":
        if self.optimizer is not None:
            normalized_optimizer = self.optimizer.strip()
            if not normalized_optimizer:
                raise ValueError("`optimizer` must not be empty")
            optimizer_kind = builtin_agent_kind(normalized_optimizer)
            if optimizer_kind is None or optimizer_kind not in _INTERACTIVE_AGENT_KINDS:
                supported = ", ".join(f"`{agent.value}`" for agent in sorted(_INTERACTIVE_AGENT_KINDS, key=lambda agent: agent.value))
                raise ValueError(f"`optimizer` must be one of {supported}")
            self.optimizer = normalized_optimizer
        elif self.n_run > 1:
            raise ValueError("`optimizer` is required when `n_run` is greater than 1")

        if not self.nodes:
            raise ValueError("pipeline must contain at least one node")

        ids = [node.id for node in self.nodes]
        duplicates = {node_id for node_id in ids if ids.count(node_id) > 1}
        if duplicates:
            raise ValueError(f"duplicate node ids: {sorted(duplicates)}")
        missing = {
            dependency
            for node in self.nodes
            for dependency in node.depends_on
            if dependency not in ids
        }
        if missing:
            raise ValueError(f"unknown dependencies: {sorted(missing)}")
        fanout_missing = {
            member_id
            for members in self.fanouts.values()
            for member_id in members
            if member_id not in ids
        }
        if fanout_missing:
            raise ValueError(f"fanout metadata references unknown nodes: {sorted(fanout_missing)}")
        node_indexes = {node.id: index for index, node in enumerate(self.nodes)}
        fanout_indexes = {
            group_id: max(node_indexes[member_id] for member_id in member_ids)
            for group_id, member_ids in self.fanouts.items()
            if member_ids
        }
        for node in self.nodes:
            if node.schedule is None:
                continue
            watched_group = node.schedule.until_fanout_settles_from
            if watched_group not in self.fanouts:
                available = ", ".join(f"`{group_id}`" for group_id in sorted(self.fanouts)) or "(none)"
                raise ValueError(
                    f"scheduled node {node.id!r} watches unknown fanout group `{watched_group}`; available fanouts: {available}"
                )
            if fanout_indexes[watched_group] >= node_indexes[node.id]:
                raise ValueError(
                    f"scheduled node {node.id!r} must appear after the watched fanout group `{watched_group}`"
                )
        return self

    @property
    def node_map(self) -> dict[str, NodeSpec]:
        return {node.id: node for node in self.nodes}

    @property
    def working_path(self) -> Path:
        return Path(self.working_dir).expanduser().resolve()

    @property
    def uses_graph_optimizer(self) -> bool:
        return self.optimizer is not None and self.n_run > 1


class NormalizedTraceEvent(BaseModel):
    model_config = ConfigDict(extra="allow")

    timestamp: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    node_id: str
    agent: AgentKind
    attempt: int = 1
    source: Literal["stdout", "stderr", "system"] = "stdout"
    kind: str
    title: str
    content: str | None = None
    raw: Any | None = None


class NodeAttempt(BaseModel):
    model_config = ConfigDict(extra="forbid")

    number: int
    status: NodeStatus = NodeStatus.PENDING
    started_at: str | None = None
    finished_at: str | None = None
    exit_code: int | None = None
    final_response: str | None = None
    output: str | None = None
    success: bool | None = None
    success_details: list[str] = Field(default_factory=list)


class NodeResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    @model_validator(mode="before")
    @classmethod
    def discard_legacy_runtime_fields(cls, data: Any) -> Any:
        if isinstance(data, dict):
            data = dict(data)
            for key in (
                "stdout_lines",
                "stderr_lines",
                "trace_events",
                "current_attempt",
                "last_tick_started_at",
                "next_scheduled_at",
            ):
                data.pop(key, None)
        return data

    node_id: str
    status: NodeStatus = NodeStatus.PENDING
    started_at: str | None = None
    finished_at: str | None = None
    exit_code: int | None = None
    final_response: str | None = None
    output: str | None = None
    success: bool | None = None
    success_details: list[str] = Field(default_factory=list)
    attempts: list[NodeAttempt] = Field(default_factory=list)
    tick_count: int = 0
    diff: str | None = None


class RunRecord(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    status: RunStatus = RunStatus.QUEUED
    pipeline: PipelineSpec
    optimization_parent_run_id: str | None = None
    optimization_round: int | None = Field(default=None, ge=1)
    optimization_session: dict[str, Any] | None = None
    created_at: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    started_at: str | None = None
    finished_at: str | None = None
    nodes: dict[str, NodeResult] = Field(default_factory=dict)


class RunEvent(BaseModel):
    model_config = ConfigDict(extra="allow")

    timestamp: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    run_id: str
    type: str
    node_id: str | None = None
    data: dict[str, Any] = Field(default_factory=dict)
