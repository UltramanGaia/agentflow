from __future__ import annotations

import re
try:
    from enum import StrEnum
except ImportError:  # pragma: no cover - Python < 3.11
    from enum import Enum

    class StrEnum(str, Enum):
        pass
from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class AgentKind(StrEnum):
    CODEX = "codex"
    CLAUDE = "claude"
    PI = "pi"
    GAIA = "gaia"
    PYTHON = "python"
    SHELL = "shell"


class ToolAccess(StrEnum):
    READ_ONLY = "read_only"
    READ_WRITE = "read_write"


class CaptureMode(StrEnum):
    FINAL = "final"
    TRACE = "trace"


class RepoInstructionsMode(StrEnum):
    INHERIT = "inherit"
    IGNORE = "ignore"


class PeriodicActuationMode(StrEnum):
    NONE = "none"
    OUTPUT_JSON = "output_json"


class NodeStatus(StrEnum):
    PENDING = "pending"
    QUEUED = "queued"
    READY = "ready"
    RUNNING = "running"
    RETRYING = "retrying"
    COMPLETED = "completed"
    FAILED = "failed"
    SKIPPED = "skipped"
    CANCELLED = "cancelled"


class RunStatus(StrEnum):
    PENDING = "pending"
    QUEUED = "queued"
    RUNNING = "running"
    CANCELLING = "cancelling"
    CANCELLED = "cancelled"
    COMPLETED = "completed"
    FAILED = "failed"


_INTERACTIVE_AGENT_KINDS = {
    AgentKind.CODEX,
    AgentKind.CLAUDE,
    AgentKind.PI,
    AgentKind.GAIA,
}


def normalize_agent_name(value: str | AgentKind) -> str:
    if isinstance(value, AgentKind):
        return value.value
    return str(value).strip()


def builtin_agent_kind(value: str | AgentKind | None) -> AgentKind | None:
    if isinstance(value, AgentKind):
        return value
    if not isinstance(value, str):
        return None
    normalized = value.strip()
    if not normalized:
        return None
    try:
        return AgentKind(normalized)
    except ValueError:
        return None

_FANOUT_ALIAS_PATTERN = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
_FANOUT_RESERVED_CONTEXT_NAMES = {"fanout", "fanouts", "nodes", "pipeline"}
_FANOUT_MEMBER_RESERVED_NAMES = {"index", "number", "count", "suffix", "value", "template_id", "node_id"}
_FANOUT_TEMPLATE_PATTERN = re.compile(r"{{\s*(?P<expr>[A-Za-z_][A-Za-z0-9_]*(?:\.[A-Za-z_][A-Za-z0-9_]*)*)\s*}}")
_FANOUT_EXPANSION_MODE_KEYS = ("count", "values", "matrix", "group_by", "batches")


class LocalTarget(BaseModel):
    model_config = ConfigDict(extra="forbid")

    cwd: str | None = None

    @model_validator(mode="before")
    @classmethod
    def validate_legacy_kind(cls, value: Any) -> Any:
        if not isinstance(value, dict):
            return value
        kind = value.get("kind")
        if kind is None:
            return value
        if kind != "local":
            raise ValueError("`target.kind` currently only supports `local`")
        normalized = dict(value)
        normalized.pop("kind", None)
        return normalized


TargetSpec = LocalTarget


class OutputContainsCriterion(BaseModel):
    kind: Literal["output_contains"] = "output_contains"
    value: str
    case_sensitive: bool = False


class OutputRegexCriterion(BaseModel):
    kind: Literal["output_regex"] = "output_regex"
    value: str
    case_sensitive: bool = True
    multiline: bool = True


class FileExistsCriterion(BaseModel):
    kind: Literal["file_exists"] = "file_exists"
    path: str


class FileContainsCriterion(BaseModel):
    kind: Literal["file_contains"] = "file_contains"
    path: str
    value: str
    case_sensitive: bool = False


class FileNonEmptyCriterion(BaseModel):
    kind: Literal["file_nonempty"] = "file_nonempty"
    path: str


class NodeOutputContainsSkipCriterion(BaseModel):
    kind: Literal["node_output_contains"] = "node_output_contains"
    node_id: str
    value: str
    case_sensitive: bool = False


SuccessCriterion = Annotated[
    OutputContainsCriterion
    | OutputRegexCriterion
    | FileExistsCriterion
    | FileContainsCriterion
    | FileNonEmptyCriterion,
    Field(discriminator="kind"),
]


SkipCriterion = Annotated[
    NodeOutputContainsSkipCriterion,
    Field(discriminator="kind"),
]


class FanoutGroupBySpec(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    from_: str = Field(alias="from")
    fields: list[str]

    @field_validator("from_")
    @classmethod
    def validate_source_group(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("`fanout.group_by.from` must not be empty")
        return normalized

    @field_validator("fields")
    @classmethod
    def validate_fields(cls, value: list[str]) -> list[str]:
        if not value:
            raise ValueError("`fanout.group_by.fields` must contain at least one field")

        normalized: list[str] = []
        seen: set[str] = set()
        for raw_field in value:
            if not isinstance(raw_field, str):
                raise ValueError("`fanout.group_by.fields` entries must be strings")
            field = raw_field.strip()
            if not field:
                raise ValueError("`fanout.group_by.fields` entries must not be empty")
            if not _FANOUT_ALIAS_PATTERN.fullmatch(field):
                raise ValueError("`fanout.group_by.fields` entries must be valid member field names")
            if field in seen:
                raise ValueError(f"`fanout.group_by.fields` contains duplicate field `{field}`")
            seen.add(field)
            normalized.append(field)
        return normalized


class FanoutBatchesSpec(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    from_: str = Field(alias="from")
    size: int = Field(gt=0)

    @field_validator("from_")
    @classmethod
    def validate_source_group(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("`fanout.batches.from` must not be empty")
        return normalized


class FanoutSpec(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    count: int | None = Field(default=None, ge=1)
    values: list[Any] | None = None
    matrix: dict[str, list[Any]] | None = None
    include: list[dict[str, Any]] | None = None
    exclude: list[dict[str, Any]] | None = None
    derive: dict[str, Any] = Field(default_factory=dict)
    as_: str = Field(default="item", alias="as")

    @field_validator("values")
    @classmethod
    def validate_values(cls, value: list[Any] | None) -> list[Any] | None:
        if value is None:
            return None
        if not value:
            raise ValueError("`fanout.values` must contain at least one item")
        return value

    @field_validator("matrix")
    @classmethod
    def validate_matrix(cls, value: dict[str, list[Any]] | None) -> dict[str, list[Any]] | None:
        if value is None:
            return None
        if not value:
            raise ValueError("`fanout.matrix` must contain at least one axis")

        normalized: dict[str, list[Any]] = {}
        for axis_name, axis_values in value.items():
            axis = axis_name.strip()
            if not axis:
                raise ValueError("`fanout.matrix` axis names must not be empty")
            if not _FANOUT_ALIAS_PATTERN.fullmatch(axis):
                raise ValueError("`fanout.matrix` axis names must be valid template variable names")
            if axis in _FANOUT_MEMBER_RESERVED_NAMES:
                raise ValueError(
                    "`fanout.matrix` axis names must not use reserved member fields such as "
                    "`index`, `number`, `count`, `suffix`, `value`, `template_id`, or `node_id`"
                )
            if axis in normalized:
                raise ValueError(f"`fanout.matrix` axis `{axis}` was provided more than once")
            if not axis_values:
                raise ValueError(f"`fanout.matrix.{axis}` must contain at least one item")
            normalized[axis] = axis_values
        return normalized

    @field_validator("include")
    @classmethod
    def validate_include(cls, value: list[dict[str, Any]] | None) -> list[dict[str, Any]] | None:
        if value is None:
            return None
        if not value:
            raise ValueError("`fanout.include` must contain at least one item")
        from agentflow.fanout import _normalize_fanout_matrix_member

        return [_normalize_fanout_matrix_member(item) for item in value]

    @field_validator("exclude")
    @classmethod
    def validate_exclude(cls, value: list[dict[str, Any]] | None) -> list[dict[str, Any]] | None:
        if value is None:
            return None
        if not value:
            raise ValueError("`fanout.exclude` must contain at least one item")
        return value

    @field_validator("derive")
    @classmethod
    def validate_derive(cls, value: dict[str, Any]) -> dict[str, Any]:
        normalized: dict[str, Any] = {}
        for field_name, field_value in value.items():
            if not isinstance(field_name, str):
                raise ValueError("`fanout.derive` field names must be strings")
            field = field_name.strip()
            if not field:
                raise ValueError("`fanout.derive` field names must not be empty")
            if not _FANOUT_ALIAS_PATTERN.fullmatch(field):
                raise ValueError("`fanout.derive` field names must be valid template variable names")
            if field in _FANOUT_MEMBER_RESERVED_NAMES:
                raise ValueError(
                    "`fanout.derive` field names must not use reserved member fields such as "
                    "`index`, `number`, `count`, `suffix`, `value`, `template_id`, or `node_id`"
                )
            normalized[field] = field_value
        return normalized

    @field_validator("as_")
    @classmethod
    def validate_alias(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("`fanout.as` must not be empty")
        if normalized in _FANOUT_RESERVED_CONTEXT_NAMES:
            raise ValueError(
                "`fanout.as` uses a reserved template variable name; choose something other than "
                "`fanout`, `fanouts`, `nodes`, `pipeline`, or `item`"
            )
        if not _FANOUT_ALIAS_PATTERN.fullmatch(normalized):
            raise ValueError("`fanout.as` must be a valid template variable name")
        return normalized

    @model_validator(mode="after")
    def validate_shape(self) -> "FanoutSpec":
        modes = (
            self.count is not None,
            self.values is not None,
            self.matrix is not None,
        )
        selected = sum(modes)
        if selected == 0:
            raise ValueError("fanout requires exactly one of `count`, `values`, or `matrix`")
        if selected > 1:
            raise ValueError("fanout accepts exactly one of `count`, `values`, or `matrix`")
        if (self.include is not None or self.exclude is not None) and self.matrix is None:
            raise ValueError("`fanout.include` and `fanout.exclude` require `fanout.matrix`")
        if self.matrix is not None:
            from agentflow.fanout import _curate_fanout_matrix_members

            if not _curate_fanout_matrix_members(
                self.matrix,
                include=self.include,
                exclude=self.exclude,
            ):
                raise ValueError("`fanout.matrix` produced no members after applying `fanout.exclude`")
        return self

    @property
    def member_values(self) -> list[Any]:
        if self.values is not None:
            return self.values
        if self.matrix is not None:
            from agentflow.fanout import _curate_fanout_matrix_members

            return _curate_fanout_matrix_members(self.matrix, include=self.include, exclude=self.exclude)
        if self.count is None:
            return []
        return list(range(self.count))

    @property
    def member_count(self) -> int:
        if self.values is not None:
            return len(self.values)
        if self.matrix is not None:
            from agentflow.fanout import _curate_fanout_matrix_members

            return len(_curate_fanout_matrix_members(self.matrix, include=self.include, exclude=self.exclude))
        if self.count is None:
            return 0
        return self.count


class PeriodicScheduleSpec(BaseModel):
    model_config = ConfigDict(extra="forbid")

    every_seconds: int = Field(ge=1)
    until_fanout_settles_from: str
    actuation: PeriodicActuationMode = PeriodicActuationMode.NONE

    @field_validator("until_fanout_settles_from")
    @classmethod
    def validate_until_fanout_settles_from(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("`schedule.until_fanout_settles_from` must not be empty")
        return normalized
