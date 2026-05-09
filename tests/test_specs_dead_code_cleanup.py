from __future__ import annotations

import pytest
from pydantic import ValidationError

from agentflow.specs import AgentKind, LocalTarget, ProviderConfig, resolve_provider


def test_resolve_provider_handles_builtin_aliases() -> None:
    assert resolve_provider("openai", AgentKind.CODEX) == ProviderConfig(name="openai")
    assert resolve_provider("anthropic", AgentKind.CLAUDE) == ProviderConfig(name="anthropic")


def test_resolve_provider_rejects_wrong_builtin_alias() -> None:
    with pytest.raises(ValueError, match="provider alias `anthropic` is not supported"):
        resolve_provider("anthropic", AgentKind.CODEX)


def test_local_target_bootstrap_remains_unsupported() -> None:
    with pytest.raises(ValidationError):
        LocalTarget.model_validate({"bootstrap": "codex"})


def test_local_target_bootstrap_field_is_removed() -> None:
    assert "bootstrap" not in LocalTarget.model_fields
