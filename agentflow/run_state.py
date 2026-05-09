from __future__ import annotations

import threading
from dataclasses import dataclass, field

from agentflow.runtime_state import NodeRuntimeState


@dataclass(slots=True)
class PeriodicNodeRuntimeState:
    tick_count: int = 0
    next_tick_at: float | None = None
    last_tick_started_at: str | None = None
    last_tick_started_mono: float | None = None


@dataclass(slots=True)
class RunControlState:
    cancel_flag: threading.Event = field(default_factory=threading.Event)
    finished: threading.Event = field(default_factory=threading.Event)
    node_cancel_flags: set[str] = field(default_factory=set)
    pending_node_reruns: set[str] = field(default_factory=set)
    node_runtime_states: dict[str, NodeRuntimeState] = field(default_factory=dict)


@dataclass(slots=True)
class RunStateRegistry:
    _lock: threading.RLock = field(default_factory=threading.RLock, init=False, repr=False)
    _runs: dict[str, RunControlState] = field(default_factory=dict, init=False, repr=False)

    def ensure_run(self, run_id: str, *, cancel_flag: threading.Event | None = None) -> RunControlState:
        with self._lock:
            state = self._runs.get(run_id)
            if state is None:
                state = RunControlState(cancel_flag=cancel_flag or threading.Event())
                self._runs[run_id] = state
            elif cancel_flag is not None:
                state.cancel_flag = cancel_flag
            return state

    def runtime_state(self, run_id: str, node_id: str) -> NodeRuntimeState:
        with self._lock:
            state = self._runs.setdefault(run_id, RunControlState())
            return state.node_runtime_states.setdefault(node_id, NodeRuntimeState())

    def runtime_states_for_run(self, run_id: str) -> dict[str, NodeRuntimeState]:
        with self._lock:
            state = self._runs.get(run_id)
            if state is None:
                return {}
            return dict(state.node_runtime_states)

    def run_cancel_flag(self, run_id: str) -> threading.Event:
        with self._lock:
            return self._runs.setdefault(run_id, RunControlState()).cancel_flag

    def run_finished_event(self, run_id: str) -> threading.Event | None:
        with self._lock:
            state = self._runs.get(run_id)
            return None if state is None else state.finished

    def mark_finished(self, run_id: str) -> None:
        with self._lock:
            state = self._runs.get(run_id)
            if state is not None:
                state.finished.set()

    def request_node_cancel(self, run_id: str, node_id: str) -> None:
        with self._lock:
            self._runs.setdefault(run_id, RunControlState()).node_cancel_flags.add(node_id)

    def discard_node_cancel(self, run_id: str, node_id: str) -> None:
        with self._lock:
            self._runs.setdefault(run_id, RunControlState()).node_cancel_flags.discard(node_id)

    def should_cancel_node(self, run_id: str, node_id: str) -> bool:
        with self._lock:
            state = self._runs.get(run_id)
            return False if state is None else node_id in state.node_cancel_flags

    def queue_node_rerun(self, run_id: str, node_id: str) -> None:
        with self._lock:
            self._runs.setdefault(run_id, RunControlState()).pending_node_reruns.add(node_id)

    def consume_pending_node_rerun(self, run_id: str, node_id: str) -> bool:
        with self._lock:
            state = self._runs.setdefault(run_id, RunControlState())
            if node_id not in state.pending_node_reruns:
                return False
            state.pending_node_reruns.discard(node_id)
            return True

    def clear_run(self, run_id: str) -> None:
        with self._lock:
            self._runs.pop(run_id, None)
