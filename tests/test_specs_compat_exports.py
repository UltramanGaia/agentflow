from __future__ import annotations

from agentflow import specs
from agentflow.pipeline_defaults import prepare_pipeline_payload
from agentflow.provider import resolve_provider
from agentflow.specs_core import AgentKind, LocalTarget, ProviderConfig
from agentflow.specs_models import NodeSpec, PipelineSpec, RunEvent, RunRecord


def test_specs_module_reexports_public_api_after_split() -> None:
    assert specs.AgentKind is AgentKind
    assert specs.LocalTarget is LocalTarget
    assert specs.ProviderConfig is ProviderConfig
    assert specs.NodeSpec is NodeSpec
    assert specs.PipelineSpec is PipelineSpec
    assert specs.RunRecord is RunRecord
    assert specs.RunEvent is RunEvent
    assert specs.resolve_provider is resolve_provider
    assert specs.prepare_pipeline_payload is prepare_pipeline_payload
