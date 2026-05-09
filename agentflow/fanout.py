from __future__ import annotations

from collections import Counter
from itertools import product
import re
from pathlib import Path
from typing import Any

from agentflow.specs_core import (
    FanoutBatchesSpec,
    FanoutGroupBySpec,
    FanoutSpec,
    _FANOUT_ALIAS_PATTERN,
    _FANOUT_EXPANSION_MODE_KEYS,
    _FANOUT_MEMBER_RESERVED_NAMES,
    _FANOUT_TEMPLATE_PATTERN,
)


def _fanout_suffix(index: int, count: int) -> str:
    width = max(1, len(str(count)))
    return str(index).zfill(width)


def _lift_fanout_member_mapping(
    member: dict[str, Any],
    mapping: dict[str, Any],
    *,
    strict: bool = False,
    source: str | None = None,
) -> None:
    for key, item in mapping.items():
        if not isinstance(key, str) or not _FANOUT_ALIAS_PATTERN.fullmatch(key):
            continue
        if key in _FANOUT_MEMBER_RESERVED_NAMES:
            if strict:
                axis_label = f" axis `{source}`" if source else ""
                raise ValueError(
                    f"fanout.matrix{axis_label} item uses reserved lifted key `{key}`; "
                    "choose a different key name"
                )
            continue
        if key in member:
            if strict and member[key] != item:
                axis_label = f" axis `{source}`" if source else ""
                raise ValueError(
                    f"fanout.matrix{axis_label} item conflicts on lifted key `{key}`; "
                    "use distinct field names across axes"
                )
            continue
        member[key] = item


def _expand_fanout_matrix(matrix: dict[str, list[Any]]) -> list[dict[str, Any]]:
    axis_names = list(matrix)
    axis_values = [matrix[axis_name] for axis_name in axis_names]
    members: list[dict[str, Any]] = []
    for combination in product(*axis_values):
        member: dict[str, Any] = {}
        for axis_name, axis_value in zip(axis_names, combination):
            if axis_name in member and member[axis_name] != axis_value:
                raise ValueError(
                    f"fanout.matrix axis `{axis_name}` conflicts with another lifted field; "
                    "rename the axis or the conflicting field"
                )
            member[axis_name] = axis_value
            if isinstance(axis_value, dict):
                _lift_fanout_member_mapping(member, axis_value, strict=True, source=axis_name)
        members.append(member)
    return members


def _normalize_fanout_matrix_member(value: dict[str, Any]) -> dict[str, Any]:
    member = dict(value)
    for key, item in value.items():
        if isinstance(item, dict):
            _lift_fanout_member_mapping(member, item, strict=True, source=key)
    return member


def _fanout_member_matches_selector(member: Any, selector: Any) -> bool:
    if isinstance(selector, dict):
        if not isinstance(member, dict):
            return False
        return all(
            key in member and _fanout_member_matches_selector(member[key], expected)
            for key, expected in selector.items()
        )
    return member == selector


def _curate_fanout_matrix_members(
    matrix: dict[str, list[Any]],
    *,
    include: list[dict[str, Any]] | None = None,
    exclude: list[dict[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    members = _expand_fanout_matrix(matrix)
    if exclude:
        members = [
            member
            for member in members
            if not any(_fanout_member_matches_selector(member, selector) for selector in exclude)
        ]
    if include:
        members.extend(dict(member) for member in include)
    return members


def _freeze_fanout_value(value: Any) -> Any:
    if isinstance(value, dict):
        return tuple((key, _freeze_fanout_value(item)) for key, item in sorted(value.items()))
    if isinstance(value, list):
        return tuple(_freeze_fanout_value(item) for item in value)
    return value


def _resolve_grouped_fanout_members(
    group_by: FanoutGroupBySpec,
    *,
    source_members: dict[str, list[dict[str, Any]]],
) -> list[dict[str, Any]]:
    members = source_members.get(group_by.from_)
    if members is None:
        raise ValueError(
            f"`fanout.group_by.from` references unknown prior fanout group `{group_by.from_}`; "
            "place the source fanout earlier in the pipeline"
        )

    grouped_members: list[dict[str, Any]] = []
    grouped_indexes: dict[Any, int] = {}
    scoped_metadata_fields = {"source_group", "source_count", "size", "member_ids", "members"}
    source_count = len(members)
    for member in members:
        grouped_member: dict[str, Any] = {}
        for field in group_by.fields:
            if field not in member:
                raise ValueError(
                    f"`fanout.group_by.fields` references `{field}`, but fanout group `{group_by.from_}` "
                    "does not expose that field"
                )
            grouped_member[field] = member[field]

        conflicting_fields = sorted(scoped_metadata_fields.intersection(grouped_member))
        if conflicting_fields:
            joined = ", ".join(f"`{field}`" for field in conflicting_fields)
            raise ValueError(
                f"`fanout.group_by.fields` cannot use reserved scoped reducer metadata fields {joined}"
            )

        frozen = _freeze_fanout_value(grouped_member)
        node_id = member.get("node_id")
        if not isinstance(node_id, str) or not node_id:
            raise ValueError(
                f"fanout group `{group_by.from_}` does not expose `node_id`, so `fanout.group_by` "
                "cannot derive scoped reducer dependencies"
            )

        grouped_index = grouped_indexes.get(frozen)
        if grouped_index is None:
            grouped_indexes[frozen] = len(grouped_members)
            grouped_members.append(
                {
                    "source_group": group_by.from_,
                    "source_count": source_count,
                    "size": 1,
                    "member_ids": [node_id],
                    "members": [dict(member)],
                    **grouped_member,
                }
            )
            continue

        grouped_members[grouped_index]["size"] += 1
        grouped_members[grouped_index]["member_ids"].append(node_id)
        grouped_members[grouped_index]["members"].append(dict(member))
    return grouped_members


def _resolve_batched_fanout_members(
    batches: FanoutBatchesSpec,
    *,
    source_members: dict[str, list[dict[str, Any]]],
) -> list[dict[str, Any]]:
    members = source_members.get(batches.from_)
    if members is None:
        raise ValueError(
            f"`fanout.batches.from` references unknown prior fanout group `{batches.from_}`; "
            "place the source fanout earlier in the pipeline"
        )

    batched_members: list[dict[str, Any]] = []
    source_count = len(members)
    for offset in range(0, source_count, batches.size):
        batch_members = [dict(member) for member in members[offset : offset + batches.size]]
        if not batch_members:
            continue

        member_ids: list[str] = []
        for member in batch_members:
            node_id = member.get("node_id")
            if not isinstance(node_id, str) or not node_id:
                raise ValueError(
                    f"fanout group `{batches.from_}` does not expose `node_id`, so `fanout.batches` "
                    "cannot derive reducer dependencies"
                )
            member_ids.append(node_id)

        first = batch_members[0]
        last = batch_members[-1]
        batched_members.append(
            {
                "source_group": batches.from_,
                "source_count": source_count,
                "size": len(batch_members),
                "member_ids": member_ids,
                "members": batch_members,
                "start_index": first["index"],
                "end_index": last["index"],
                "start_number": first["number"],
                "end_number": last["number"],
                "start_suffix": first["suffix"],
                "end_suffix": last["suffix"],
            }
        )
    return batched_members


def _fanout_dependency_overrides(member: dict[str, Any]) -> dict[str, list[str]]:
    source_group = member.get("source_group")
    member_ids = member.get("member_ids")
    if not isinstance(source_group, str) or not source_group:
        return {}
    if not isinstance(member_ids, list):
        return {}

    scoped_member_ids = [member_id for member_id in member_ids if isinstance(member_id, str) and member_id]
    if not scoped_member_ids:
        return {}
    return {source_group: scoped_member_ids}


def _fanout_iteration_context(template_id: str, fanout: FanoutSpec, index: int, value: Any) -> dict[str, Any]:
    member_count = fanout.member_count
    suffix = _fanout_suffix(index, member_count)
    member = {
        "index": index,
        "number": index + 1,
        "count": member_count,
        "suffix": suffix,
        "value": value,
        "template_id": template_id,
        "node_id": f"{template_id}_{suffix}",
    }
    if isinstance(value, dict):
        _lift_fanout_member_mapping(member, value)
    context = {fanout.as_: member, "fanout": member}
    for key, raw_value in fanout.derive.items():
        if key in member:
            raise ValueError(
                f"fanout.derive field `{key}` conflicts with an existing member field; choose a different name"
            )
        member[key] = _render_fanout_value(raw_value, context)
    return context


def _render_fanout_value(value: Any, context: dict[str, Any]) -> Any:
    if isinstance(value, str):
        return _render_fanout_string(value, context)
    if isinstance(value, list):
        return [_render_fanout_value(item, context) for item in value]
    if isinstance(value, dict):
        return {key: _render_fanout_value(item, context) for key, item in value.items()}
    return value


def _resolve_fanout_template_expression(context: dict[str, Any], expression: str) -> Any:
    current: Any = context
    for part in expression.split("."):
        if isinstance(current, dict) and part in current:
            current = current[part]
            continue
        raise KeyError(expression)
    return current


def _render_fanout_string(template_text: str, context: dict[str, Any]) -> str:
    def _replace(match: re.Match[str]) -> str:
        expression = match.group("expr")
        root = expression.split(".", 1)[0]
        if root not in context:
            return match.group(0)
        try:
            resolved = _resolve_fanout_template_expression(context, expression)
        except KeyError:
            return match.group(0)
        return str(resolved)

    return _FANOUT_TEMPLATE_PATTERN.sub(_replace, template_text)


def _resolve_fanout_manifest_modes(raw_fanout: Any) -> Any:
    if not isinstance(raw_fanout, dict):
        return raw_fanout

    updated = dict(raw_fanout)
    selected_modes = [key for key in _FANOUT_EXPANSION_MODE_KEYS if updated.get(key) is not None]
    if len(selected_modes) > 1:
        joined = ", ".join(f"`{key}`" for key in _FANOUT_EXPANSION_MODE_KEYS)
        raise ValueError(f"fanout accepts exactly one of {joined}")

    return updated


def _resolve_fanout_source_modes(raw_fanout: Any, *, source_members: dict[str, list[dict[str, Any]]]) -> Any:
    if not isinstance(raw_fanout, dict):
        return raw_fanout

    updated = dict(raw_fanout)
    raw_group_by = updated.pop("group_by", None)
    raw_batches = updated.pop("batches", None)
    if raw_group_by is not None and raw_batches is not None:
        joined = ", ".join(f"`{key}`" for key in _FANOUT_EXPANSION_MODE_KEYS)
        raise ValueError(f"fanout accepts exactly one of {joined}")

    if raw_group_by is not None:
        group_by = FanoutGroupBySpec.model_validate(raw_group_by)
        updated["values"] = _resolve_grouped_fanout_members(group_by, source_members=source_members)

    if raw_batches is not None:
        batches = FanoutBatchesSpec.model_validate(raw_batches)
        updated["values"] = _resolve_batched_fanout_members(batches, source_members=source_members)
    return updated


def _expand_fanout_node(node: dict[str, Any], fanout: FanoutSpec) -> tuple[list[dict[str, Any]], list[str]]:
    template_id = node.get("id")
    if not isinstance(template_id, str) or not template_id.strip():
        raise ValueError("fanout nodes require a non-empty string `id`")
    if any(marker in template_id for marker in ("{{", "{%", "{#")):
        raise ValueError("fanout node `id` must be a literal group name, not a rendered template")

    node_template = dict(node)
    node_template.pop("fanout", None)
    expanded_nodes: list[dict[str, Any]] = []
    member_ids: list[str] = []
    for index, value in enumerate(fanout.member_values):
        iteration_context = _fanout_iteration_context(template_id, fanout, index, value)
        expanded = _render_fanout_value(node_template, iteration_context)
        if not isinstance(expanded, dict):
            raise ValueError(f"fanout node {template_id!r} did not expand into an object")
        member_id = iteration_context["fanout"]["node_id"]
        expanded["id"] = member_id
        expanded["fanout_group"] = template_id
        expanded["fanout_member"] = dict(iteration_context["fanout"])
        fanout_dependencies = _fanout_dependency_overrides(iteration_context["fanout"])
        if fanout_dependencies:
            expanded["fanout_dependencies"] = fanout_dependencies
        expanded_nodes.append(expanded)
        member_ids.append(member_id)
    return expanded_nodes, member_ids


def _expand_fanout_dependencies(nodes: list[Any], fanouts: dict[str, list[str]]) -> list[Any]:
    expanded_nodes: list[Any] = []
    for node in nodes:
        if not isinstance(node, dict):
            expanded_nodes.append(node)
            continue
        depends_on = node.get("depends_on")
        if not isinstance(depends_on, list):
            expanded_nodes.append(node)
            continue
        updated = dict(node)
        dependency_overrides = updated.get("fanout_dependencies")
        rewritten: list[Any] = []
        for dependency in depends_on:
            if isinstance(dependency, str) and dependency in fanouts:
                if isinstance(dependency_overrides, dict):
                    scoped_members = dependency_overrides.get(dependency)
                    if isinstance(scoped_members, list) and scoped_members:
                        rewritten.extend(scoped_members)
                        continue
                rewritten.extend(fanouts[dependency])
                continue
            rewritten.append(dependency)
        updated["depends_on"] = rewritten
        expanded_nodes.append(updated)
    return expanded_nodes


def expand_compact_nodes(payload: dict[str, Any], *, base_dir: str | Path | None = None) -> dict[str, Any]:
    resolved = dict(payload)
    nodes = resolved.get("nodes")
    if not isinstance(nodes, list):
        return resolved
    source_ids = [node.get("id") for node in nodes if isinstance(node, dict) and isinstance(node.get("id"), str)]
    duplicate_source_ids = {node_id for node_id, count in Counter(source_ids).items() if count > 1}
    if duplicate_source_ids:
        raise ValueError(f"duplicate node ids: {sorted(duplicate_source_ids)}")

    fanouts: dict[str, list[str]] = {}
    raw_fanouts = resolved.get("fanouts")
    if isinstance(raw_fanouts, dict):
        fanouts = {
            str(group_id): [str(member_id) for member_id in members]
            for group_id, members in raw_fanouts.items()
            if isinstance(group_id, str) and isinstance(members, list)
        }
    saw_fanout = False
    expanded_nodes: list[Any] = []
    fanout_members: dict[str, list[dict[str, Any]]] = {}
    for node in nodes:
        if not isinstance(node, dict):
            expanded_nodes.append(node)
            continue
        raw_fanout = node.get("fanout")
        if raw_fanout is None:
            expanded_nodes.append(dict(node))
            continue
        saw_fanout = True
        resolved_fanout = _resolve_fanout_manifest_modes(raw_fanout)
        resolved_fanout = _resolve_fanout_source_modes(resolved_fanout, source_members=fanout_members)
        fanout = FanoutSpec.model_validate(resolved_fanout)
        rendered_nodes, member_ids = _expand_fanout_node(node, fanout)
        fanouts[str(node.get("id"))] = member_ids
        fanout_members[str(node.get("id"))] = [
            dict(rendered_node["fanout_member"])
            for rendered_node in rendered_nodes
            if isinstance(rendered_node, dict) and isinstance(rendered_node.get("fanout_member"), dict)
        ]
        expanded_nodes.extend(rendered_nodes)

    if not saw_fanout:
        return resolved

    resolved["fanouts"] = fanouts
    resolved["nodes"] = _expand_fanout_dependencies(expanded_nodes, fanouts)
    return resolved
