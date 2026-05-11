from __future__ import annotations

from agentflow.agents.base import AgentAdapter
from agentflow.agents.gaia import GaiaAdapter
from agentflow.agents.python import PythonAdapter
from agentflow.agents.shell import ShellAdapter
from agentflow.specs import AgentKind


def build_default_adapters() -> dict[AgentKind, AgentAdapter]:
    return {
        AgentKind.GAIA: GaiaAdapter(),
        AgentKind.PYTHON: PythonAdapter(),
        AgentKind.SHELL: ShellAdapter(),
    }


def get_default_adapter(kind: AgentKind) -> AgentAdapter:
    return build_default_adapters()[kind]


__all__ = ["AgentAdapter", "build_default_adapters", "get_default_adapter"]
