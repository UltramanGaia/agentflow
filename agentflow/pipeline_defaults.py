from __future__ import annotations

from copy import deepcopy
from pathlib import Path
from typing import Any

from agentflow.fanout import expand_compact_nodes
from agentflow.specs_core import AgentKind, LocalTarget, builtin_agent_kind


_NODE_DEFAULT_FORBIDDEN_FIELDS = {
    "id",
    "prompt",
    "depends_on",
    "fanout",
    "fanout_group",
    "fanout_member",
    "fanout_dependencies",
}
_NODE_DEFAULT_LIST_MERGE_FIELDS = {"extra_args", "skills"}
_NODE_DEFAULT_DICT_MERGE_FIELDS = {"provider"}


def _local_target_defaults_payload(value: Any) -> dict[str, Any] | None:
    if isinstance(value, LocalTarget):
        payload = value.model_dump(mode="python")
    elif isinstance(value, dict):
        payload = dict(value)
    else:
        return None
    payload.setdefault("kind", "local")
    return payload


def _node_default_payload(
    value: Any,
    *,
    subject: str,
    allow_agent: bool,
) -> dict[str, Any] | None:
    if value is None:
        return None
    if not isinstance(value, dict):
        raise ValueError(f"`{subject}` must be an object")

    from agentflow.specs_models import NodeSpec

    allowed = set(NodeSpec.model_fields) - _NODE_DEFAULT_FORBIDDEN_FIELDS
    if not allow_agent:
        allowed.discard("agent")

    unknown = sorted(set(value) - allowed)
    if unknown:
        supported = ", ".join(f"`{field}`" for field in sorted(allowed))
        unknown_display = ", ".join(f"`{field}`" for field in unknown)
        raise ValueError(f"`{subject}` does not support {unknown_display}; supported fields: {supported}")

    return dict(value)


def _merge_default_target_payload(default_value: Any, override_value: Any) -> Any:
    if not isinstance(default_value, dict) or not isinstance(override_value, dict):
        return deepcopy(override_value)

    default_kind = default_value.get("kind")
    override_kind = override_value.get("kind")
    if default_kind and override_kind and default_kind != override_kind:
        return deepcopy(override_value)

    merged = deepcopy(default_value)
    merged.update(deepcopy(override_value))
    return merged


def _merge_node_payloads(defaults: dict[str, Any], overrides: dict[str, Any]) -> dict[str, Any]:
    merged = deepcopy(defaults)
    for key, value in overrides.items():
        if key == "target":
            merged[key] = _merge_default_target_payload(merged.get(key), value)
            continue
        if (
            key in _NODE_DEFAULT_LIST_MERGE_FIELDS
            and isinstance(merged.get(key), list)
            and isinstance(value, list)
        ):
            merged[key] = [*deepcopy(merged[key]), *deepcopy(value)]
            continue
        if (
            key in _NODE_DEFAULT_DICT_MERGE_FIELDS
            and isinstance(merged.get(key), dict)
            and isinstance(value, dict)
        ):
            merged[key] = {**deepcopy(merged[key]), **deepcopy(value)}
            continue
        merged[key] = deepcopy(value)
    return merged


def apply_node_defaults(payload: dict[str, Any]) -> dict[str, Any]:
    resolved = dict(payload)
    node_defaults = _node_default_payload(
        resolved.get("node_defaults"),
        subject="node_defaults",
        allow_agent=True,
    )
    raw_agent_defaults = resolved.get("agent_defaults")
    if raw_agent_defaults is None:
        agent_defaults: dict[AgentKind, dict[str, Any]] = {}
    else:
        if not isinstance(raw_agent_defaults, dict):
            raise ValueError("`agent_defaults` must be an object keyed by agent name")
        agent_defaults = {}
        for raw_agent, defaults in raw_agent_defaults.items():
            try:
                agent = raw_agent if isinstance(raw_agent, AgentKind) else AgentKind(str(raw_agent).strip())
            except ValueError as exc:
                supported = ", ".join(f"`{agent.value}`" for agent in AgentKind)
                raise ValueError(f"`agent_defaults` has unknown agent `{raw_agent}`; supported keys: {supported}") from exc
            normalized = _node_default_payload(
                defaults,
                subject=f"agent_defaults.{agent.value}",
                allow_agent=False,
            )
            if normalized is not None:
                agent_defaults[agent] = normalized

    if node_defaults is None and not agent_defaults:
        return resolved

    nodes = resolved.get("nodes")
    if not isinstance(nodes, list):
        return resolved

    merged_nodes: list[Any] = []
    for node in nodes:
        if not isinstance(node, dict):
            merged_nodes.append(node)
            continue

        merged_node = deepcopy(node_defaults or {})
        raw_agent = node.get("agent", merged_node.get("agent"))
        if raw_agent is not None:
            agent = builtin_agent_kind(raw_agent)
            if agent is not None:
                merged_node = _merge_node_payloads(merged_node, agent_defaults.get(agent, {}))
        merged_nodes.append(_merge_node_payloads(merged_node, dict(node)))

    resolved["nodes"] = merged_nodes
    if node_defaults is not None:
        resolved["node_defaults"] = node_defaults
    if agent_defaults:
        resolved["agent_defaults"] = {agent.value: defaults for agent, defaults in agent_defaults.items()}
    return resolved

def apply_local_target_defaults(payload: dict[str, Any]) -> dict[str, Any]:
    resolved = dict(payload)
    local_target_defaults = _local_target_defaults_payload(resolved.get("local_target_defaults"))

    nodes = resolved.get("nodes")
    if not isinstance(nodes, list):
        return resolved

    merged_nodes: list[Any] = []
    for node in nodes:
        if not isinstance(node, dict):
            merged_nodes.append(node)
            continue

        updated_node = dict(node)
        target = updated_node.get("target")
        if target is None:
            if local_target_defaults is None:
                merged_nodes.append(updated_node)
                continue
            updated_node["target"] = dict(local_target_defaults)
            merged_nodes.append(updated_node)
            continue

        target_payload = _local_target_defaults_payload(target)
        if target_payload is None:
            merged_nodes.append(updated_node)
            continue
        if local_target_defaults is None:
            updated_node["target"] = target_payload
            merged_nodes.append(updated_node)
            continue

        if target_payload.get("kind", local_target_defaults.get("kind", "local")) != "local":
            merged_nodes.append(updated_node)
            continue

        merged_target = dict(local_target_defaults)
        merged_target.update(target_payload)
        updated_node["target"] = merged_target
        merged_nodes.append(updated_node)

    resolved["nodes"] = merged_nodes
    return resolved


def prepare_pipeline_payload(payload: dict[str, Any], *, base_dir: str | Path | None = None) -> dict[str, Any]:
    expanded = expand_compact_nodes(payload, base_dir=base_dir)
    expanded = apply_node_defaults(expanded)
    return apply_local_target_defaults(expanded)
