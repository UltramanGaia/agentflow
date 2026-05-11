"""Tests for fanout expansion, merge reduction, and dependency rewriting."""

from __future__ import annotations

import pytest

from agentflow.fanout import (
    _curate_fanout_matrix_members,
    _expand_fanout_matrix,
    _fanout_dependency_overrides,
    _fanout_iteration_context,
    _fanout_member_matches_selector,
    _fanout_suffix,
    _freeze_fanout_value,
    _normalize_fanout_matrix_member,
    _render_fanout_string,
    _render_fanout_value,
    _resolve_fanout_template_expression,
    expand_compact_nodes,
)
from agentflow.specs_core import (
    FanoutBatchesSpec,
    FanoutGroupBySpec,
    FanoutSpec,
)


# ---------------------------------------------------------------------------
# _fanout_suffix
# ---------------------------------------------------------------------------

class TestFanoutSuffix:
    def test_single_digit_count(self) -> None:
        assert _fanout_suffix(0, 5) == "0"
        assert _fanout_suffix(4, 5) == "4"

    def test_double_digit_count(self) -> None:
        assert _fanout_suffix(0, 10) == "00"
        assert _fanout_suffix(9, 10) == "09"
        assert _fanout_suffix(10, 100) == "010"

    def test_triple_digit_count(self) -> None:
        assert _fanout_suffix(0, 128) == "000"
        assert _fanout_suffix(127, 128) == "127"


# ---------------------------------------------------------------------------
# _expand_fanout_matrix
# ---------------------------------------------------------------------------

class TestExpandFanoutMatrix:
    def test_single_axis(self) -> None:
        members = _expand_fanout_matrix({"target": ["a", "b", "c"]})
        assert len(members) == 3
        assert members[0] == {"target": "a"}
        assert members[1] == {"target": "b"}
        assert members[2] == {"target": "c"}

    def test_two_axis_cartesian(self) -> None:
        members = _expand_fanout_matrix({"x": [1, 2], "y": ["a", "b"]})
        assert len(members) == 4

    def test_dict_value_lifts_keys(self) -> None:
        members = _expand_fanout_matrix({
            "family": [{"target": "libpng", "corpus": "png"}, {"target": "sqlite", "corpus": "sql"}],
        })
        assert len(members) == 2
        assert members[0]["target"] == "libpng"
        assert members[0]["corpus"] == "png"

    def test_empty_axis_returns_empty(self) -> None:
        # _expand_fanout_matrix returns empty list for empty axes
        # validation is handled by FanoutSpec.model_validate()
        members = _expand_fanout_matrix({"x": []})
        assert len(members) == 0


# ---------------------------------------------------------------------------
# _curate_fanout_matrix_members
# ---------------------------------------------------------------------------

class TestCurateFanoutMatrixMembers:
    def test_exclude_removes_matching(self) -> None:
        matrix = {"x": [1, 2, 3]}
        members = _curate_fanout_matrix_members(matrix, exclude=[{"x": 2}])
        assert len(members) == 2
        assert members[0]["x"] == 1
        assert members[1]["x"] == 3

    def test_include_appends_entries(self) -> None:
        matrix = {"x": [1, 2]}
        members = _curate_fanout_matrix_members(matrix, include=[{"x": 99}])
        assert len(members) == 3

    def test_exclude_all_yields_empty(self) -> None:
        matrix = {"x": [1]}
        members = _curate_fanout_matrix_members(matrix, exclude=[{"x": 1}])
        assert len(members) == 0


# ---------------------------------------------------------------------------
# _fanout_member_matches_selector
# ---------------------------------------------------------------------------

class TestFanoutMemberMatchesSelector:
    def test_scalar_match(self) -> None:
        assert _fanout_member_matches_selector(1, 1)
        assert not _fanout_member_matches_selector(1, 2)

    def test_dict_match(self) -> None:
        member = {"target": "libpng", "corpus": "png"}
        assert _fanout_member_matches_selector(member, {"target": "libpng"})
        assert not _fanout_member_matches_selector(member, {"target": "sqlite"})

    def test_nested_dict_match(self) -> None:
        member = {"target": "libpng", "meta": {"level": 1}}
        assert _fanout_member_matches_selector(member, {"meta": {"level": 1}})
        assert not _fanout_member_matches_selector(member, {"meta": {"level": 2}})


# ---------------------------------------------------------------------------
# _freeze_fanout_value
# ---------------------------------------------------------------------------

class TestFreezeFanoutValue:
    def test_scalar(self) -> None:
        assert _freeze_fanout_value(1) == 1
        assert _freeze_fanout_value("a") == "a"

    def test_dict_sorts_keys(self) -> None:
        frozen = _freeze_fanout_value({"b": 2, "a": 1})
        assert frozen == (("a", 1), ("b", 2))

    def test_list(self) -> None:
        frozen = _freeze_fanout_value([1, 2])
        assert frozen == (1, 2)

    def test_nested(self) -> None:
        frozen = _freeze_fanout_value({"x": [1]})
        assert frozen == (("x", (1,)),)


# ---------------------------------------------------------------------------
# _render_fanout_string
# ---------------------------------------------------------------------------

class TestRenderFanoutString:
    def test_simple_variable(self) -> None:
        context = {"item": {"number": 5}}
        assert _render_fanout_string("{{ item.number }}", context) == "5"

    def test_missing_variable_left_as_is(self) -> None:
        assert _render_fanout_string("{{ item.missing }}", {"item": {}}) == "{{ item.missing }}"

    def test_root_not_in_context(self) -> None:
        assert _render_fanout_string("{{ other.value }}", {"item": {}}) == "{{ other.value }}"

    def test_multiple_templates(self) -> None:
        context = {"item": {"a": "x", "b": "y"}}
        result = _render_fanout_string("{{ item.a }}-{{ item.b }}", context)
        assert result == "x-y"


# ---------------------------------------------------------------------------
# _resolve_fanout_template_expression
# ---------------------------------------------------------------------------

class TestResolveFanoutTemplateExpression:
    def test_simple(self) -> None:
        assert _resolve_fanout_template_expression({"item": {"number": 5}}, "item.number") == 5

    def test_missing_key_raises(self) -> None:
        with pytest.raises(KeyError):
            _resolve_fanout_template_expression({"item": {}}, "item.missing")


# ---------------------------------------------------------------------------
# FanoutSpec validation
# ---------------------------------------------------------------------------

class TestFanoutSpec:
    def test_count_mode(self) -> None:
        spec = FanoutSpec.model_validate({"count": 10})
        assert spec.count == 10
        assert spec.member_count == 10

    def test_values_mode(self) -> None:
        spec = FanoutSpec.model_validate({"values": [{"x": 1}, {"x": 2}]})
        assert spec.member_count == 2

    def test_matrix_mode(self) -> None:
        spec = FanoutSpec.model_validate({"matrix": {"a": [1, 2], "b": ["x"]}})
        assert spec.member_count == 2

    def test_no_mode_raises(self) -> None:
        with pytest.raises(ValueError, match="exactly one"):
            FanoutSpec.model_validate({})

    def test_multiple_modes_raises(self) -> None:
        with pytest.raises(ValueError, match="exactly one"):
            FanoutSpec.model_validate({"count": 5, "values": [1]})

    def test_include_without_matrix_raises(self) -> None:
        with pytest.raises(ValueError, match="require `fanout.matrix`"):
            FanoutSpec.model_validate({"count": 5, "include": [{"x": 1}]})

    def test_exclude_without_matrix_raises(self) -> None:
        with pytest.raises(ValueError, match="require `fanout.matrix`"):
            FanoutSpec.model_validate({"count": 5, "exclude": [{"x": 1}]})

    def test_empty_values_raises(self) -> None:
        with pytest.raises(ValueError, match="at least one item"):
            FanoutSpec.model_validate({"values": []})

    def test_empty_matrix_raises(self) -> None:
        with pytest.raises(ValueError, match="at least one axis"):
            FanoutSpec.model_validate({"matrix": {}})

    def test_matrix_empty_axis_raises(self) -> None:
        with pytest.raises(ValueError, match="at least one item"):
            FanoutSpec.model_validate({"matrix": {"a": []}})

    def test_reserved_alias_raises(self) -> None:
        with pytest.raises(ValueError, match="reserved"):
            FanoutSpec.model_validate({"count": 2, "as": "nodes"})

    def test_reserved_derive_field_raises(self) -> None:
        with pytest.raises(ValueError, match="reserved"):
            FanoutSpec.model_validate({"count": 2, "derive": {"index": "bad"}})

    def test_reserved_matrix_axis_raises(self) -> None:
        with pytest.raises(ValueError, match="reserved"):
            FanoutSpec.model_validate({"matrix": {"index": [1, 2]}})

    def test_custom_alias(self) -> None:
        spec = FanoutSpec.model_validate({"count": 3, "as": "shard"})
        assert spec.as_ == "shard"

    def test_derive_field(self) -> None:
        spec = FanoutSpec.model_validate({"count": 2, "derive": {"label": "test-{{ item.number }}"}})
        assert spec.derive["label"] == "test-{{ item.number }}"


# ---------------------------------------------------------------------------
# _fanout_iteration_context
# ---------------------------------------------------------------------------

class TestFanoutIterationContext:
    def test_uniform_count_context(self) -> None:
        spec = FanoutSpec.model_validate({"count": 128})
        ctx = _fanout_iteration_context("fuzzer", spec, 5, None)
        member = ctx["item"]
        assert member["index"] == 5
        assert member["number"] == 6
        assert member["count"] == 128
        assert member["suffix"] == "005"
        assert member["node_id"] == "fuzzer_005"

    def test_values_context(self) -> None:
        spec = FanoutSpec.model_validate({"values": ["a", "b", "c"]})
        ctx = _fanout_iteration_context("review", spec, 1, "b")
        member = ctx["item"]
        assert member["value"] == "b"
        assert member["number"] == 2
        assert member["node_id"] == "review_1"

    def test_dict_value_lifts_keys(self) -> None:
        spec = FanoutSpec.model_validate({"values": [{"file": "api.py"}]})
        ctx = _fanout_iteration_context("review", spec, 0, {"file": "api.py"})
        member = ctx["item"]
        assert member["file"] == "api.py"

    def test_derive_rendering(self) -> None:
        spec = FanoutSpec.model_validate({"count": 3, "derive": {"label": "item-{{ item.number }}"}}
        )
        ctx = _fanout_iteration_context("test", spec, 0, None)
        assert ctx["item"]["label"] == "item-1"


# ---------------------------------------------------------------------------
# _fanout_dependency_overrides
# ---------------------------------------------------------------------------

class TestFanoutDependencyOverrides:
    def test_reducer_member(self) -> None:
        member = {"source_group": "fuzzer", "member_ids": ["fuzzer_000", "fuzzer_001"]}
        overrides = _fanout_dependency_overrides(member)
        assert overrides == {"fuzzer": ["fuzzer_000", "fuzzer_001"]}

    def test_non_reducer_member(self) -> None:
        member = {"index": 0, "number": 1}
        assert _fanout_dependency_overrides(member) == {}

    def test_empty_member_ids(self) -> None:
        member = {"source_group": "fuzzer", "member_ids": []}
        assert _fanout_dependency_overrides(member) == {}


# ---------------------------------------------------------------------------
# expand_compact_nodes (integration-level)
# ---------------------------------------------------------------------------

class TestExpandCompactNodes:
    def test_no_fanout_passes_through(self) -> None:
        payload = {
            "name": "test",
            "nodes": [
                {"id": "a", "agent": "gaia", "prompt": "do a"},
                {"id": "b", "agent": "gaia", "prompt": "do b", "depends_on": ["a"]},
            ],
        }
        result = expand_compact_nodes(payload)
        assert len(result["nodes"]) == 2

    def test_uniform_fanout_expands(self) -> None:
        payload = {
            "name": "test",
            "nodes": [
                {"id": "scan", "agent": "gaia", "prompt": "scan"},
                {
                    "id": "fuzzer",
                    "agent": "gaia",
                    "prompt": "fuzz {{ item.number }}",
                    "fanout": {"count": 4},
                },
            ],
        }
        result = expand_compact_nodes(payload)
        fuzzer_nodes = [n for n in result["nodes"] if n.get("fanout_group") == "fuzzer"]
        assert len(fuzzer_nodes) == 4
        assert "fuzzer" in result["fanouts"]
        assert len(result["fanouts"]["fuzzer"]) == 4

    def test_values_fanout_expands(self) -> None:
        payload = {
            "name": "test",
            "nodes": [
                {
                    "id": "review",
                    "agent": "gaia",
                    "prompt": "review {{ item.file }}",
                    "fanout": {"values": [{"file": "api.py"}, {"file": "db.py"}]},
                },
            ],
        }
        result = expand_compact_nodes(payload)
        review_nodes = [n for n in result["nodes"] if n.get("fanout_group") == "review"]
        assert len(review_nodes) == 2

    def test_matrix_fanout_cartesian(self) -> None:
        payload = {
            "name": "test",
            "nodes": [
                {
                    "id": "fuzzer",
                    "agent": "gaia",
                    "prompt": "fuzz",
                    "fanout": {"matrix": {"target": ["a", "b"], "mode": ["asan", "ubsan"]}},
                },
            ],
        }
        result = expand_compact_nodes(payload)
        fuzzer_nodes = [n for n in result["nodes"] if n.get("fanout_group") == "fuzzer"]
        assert len(fuzzer_nodes) == 4

    def test_fanout_dependencies_rewrite(self) -> None:
        payload = {
            "name": "test",
            "nodes": [
                {"id": "init", "agent": "gaia", "prompt": "init"},
                {
                    "id": "worker",
                    "agent": "gaia",
                    "prompt": "work",
                    "fanout": {"count": 3},
                    "depends_on": ["init"],
                },
                {"id": "merge", "agent": "gaia", "prompt": "merge", "depends_on": ["worker"]},
            ],
        }
        result = expand_compact_nodes(payload)
        merge_node = [n for n in result["nodes"] if n["id"] == "merge"][0]
        assert set(merge_node["depends_on"]) == set(result["fanouts"]["worker"])

    def test_duplicate_source_ids_raises(self) -> None:
        payload = {
            "name": "test",
            "nodes": [
                {"id": "dup", "agent": "gaia", "prompt": "a"},
                {"id": "dup", "agent": "gaia", "prompt": "b"},
            ],
        }
        with pytest.raises(ValueError, match="duplicate node ids"):
            expand_compact_nodes(payload)

    def test_batch_merge_expands(self) -> None:
        payload = {
            "name": "test",
            "nodes": [
                {
                    "id": "worker",
                    "agent": "gaia",
                    "prompt": "work",
                    "fanout": {"count": 4},
                },
                {
                    "id": "batch_merge",
                    "agent": "gaia",
                    "prompt": "merge {{ item.source_group }}",
                    "fanout": {"batches": {"from": "worker", "size": 2}},
                    "depends_on": ["worker"],
                },
            ],
        }
        result = expand_compact_nodes(payload)
        merge_nodes = [n for n in result["nodes"] if n.get("fanout_group") == "batch_merge"]
        assert len(merge_nodes) == 2
        # Each batch should have 2 member_ids
        for node in merge_nodes:
            assert len(node["fanout_member"]["member_ids"]) == 2

    def test_group_by_merge_expands(self) -> None:
        payload = {
            "name": "test",
            "nodes": [
                {
                    "id": "worker",
                    "agent": "gaia",
                    "prompt": "work",
                    "fanout": {
                        "values": [
                            {"target": "a", "mode": "x"},
                            {"target": "a", "mode": "y"},
                            {"target": "b", "mode": "x"},
                        ],
                    },
                },
                {
                    "id": "family_merge",
                    "agent": "gaia",
                    "prompt": "merge by target",
                    "fanout": {"group_by": {"from": "worker", "fields": ["target"]}},
                    "depends_on": ["worker"],
                },
            ],
        }
        result = expand_compact_nodes(payload)
        merge_nodes = [n for n in result["nodes"] if n.get("fanout_group") == "family_merge"]
        assert len(merge_nodes) == 2  # one for "a", one for "b"


# ---------------------------------------------------------------------------
# FanoutGroupBySpec / FanoutBatchesSpec
# ---------------------------------------------------------------------------

class TestFanoutGroupBySpec:
    def test_valid(self) -> None:
        spec = FanoutGroupBySpec.model_validate({"from": "worker", "fields": ["target"]})
        assert spec.from_ == "worker"
        assert spec.fields == ["target"]

    def test_empty_from_raises(self) -> None:
        with pytest.raises(ValueError, match="must not be empty"):
            FanoutGroupBySpec.model_validate({"from": "  ", "fields": ["target"]})

    def test_empty_fields_raises(self) -> None:
        with pytest.raises(ValueError, match="at least one"):
            FanoutGroupBySpec.model_validate({"from": "worker", "fields": []})

    def test_duplicate_fields_raises(self) -> None:
        with pytest.raises(ValueError, match="duplicate"):
            FanoutGroupBySpec.model_validate({"from": "worker", "fields": ["target", "target"]})


class TestFanoutBatchesSpec:
    def test_valid(self) -> None:
        spec = FanoutBatchesSpec.model_validate({"from": "worker", "size": 16})
        assert spec.from_ == "worker"
        assert spec.size == 16

    def test_empty_from_raises(self) -> None:
        with pytest.raises(ValueError, match="must not be empty"):
            FanoutBatchesSpec.model_validate({"from": "", "size": 10})

    def test_zero_size_raises(self) -> None:
        with pytest.raises(ValueError):
            FanoutBatchesSpec.model_validate({"from": "worker", "size": 0})
