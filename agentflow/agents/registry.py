from __future__ import annotations

from agentflow.agents.base import AgentAdapter
from agentflow.agents.gaia import GaiaAdapter
from agentflow.agents.util import PythonAdapter, ShellAdapter
from agentflow.specs import AgentKind


class AdapterRegistry:
    def __init__(self) -> None:
        self._registry: dict[AgentKind, AgentAdapter] = {
            AgentKind.GAIA: GaiaAdapter(),
            AgentKind.PYTHON: PythonAdapter(),
            AgentKind.SHELL: ShellAdapter(),
        }

    def register(self, kind: AgentKind, adapter: AgentAdapter) -> None:
        self._registry[kind] = adapter

    def get(self, kind: AgentKind) -> AgentAdapter:
        return self._registry[kind]


default_adapter_registry = AdapterRegistry()
