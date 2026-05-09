from __future__ import annotations

from agentflow.specs_core import AgentKind, ProviderConfig, builtin_agent_kind


def resolve_provider(value: str | ProviderConfig | None, agent: str | AgentKind) -> ProviderConfig | None:
    if value is None:
        return None
    if isinstance(value, ProviderConfig):
        return value

    resolved_agent = builtin_agent_kind(agent)
    if resolved_agent is None:
        return ProviderConfig(name=value)

    alias = value.strip().lower()
    if alias == "openai" and resolved_agent == AgentKind.CODEX:
        return ProviderConfig(name="openai")
    if alias == "anthropic" and resolved_agent == AgentKind.CLAUDE:
        return ProviderConfig(name="anthropic")
    raise ValueError(f"provider alias `{value}` is not supported")
