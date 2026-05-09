from __future__ import annotations

import asyncio
import json
import logging
import queue
import threading
from collections import defaultdict
from pathlib import Path
from uuid import uuid4

from pydantic import ValidationError

from agentflow.specs import RunEvent, RunRecord, RunStatus
from agentflow.utils import ensure_dir

# Set up a dedicated logger for sync issues
sync_logger = logging.getLogger("agentflow.sync")


_TERMINAL_RUN_STATUSES = {RunStatus.COMPLETED, RunStatus.FAILED, RunStatus.CANCELLED}


class RunStore:
    """In-memory run registry with filesystem persistence.

    The in-memory ``_runs`` map is the runtime source of truth while this
    process is active. ``run.json`` and ``events.jsonl`` are loaded during
    initialization and written after mutations; live reads do not reconcile
    against disk.
    """

    def __init__(self, base_dir: str | Path = ".agentflow/runs") -> None:
        self.base_dir = ensure_dir(Path(base_dir).expanduser())
        self._runs: dict[str, RunRecord] = {}
        self._locks: defaultdict[str, threading.Lock] = defaultdict(threading.Lock)
        self._registry_lock = threading.RLock()
        self._subscribers: defaultdict[str, set[queue.Queue[RunEvent]]] = defaultdict(set)
        self._events_cache: defaultdict[str, list[RunEvent]] = defaultdict(list)
        self._load_existing_runs()

    def _load_existing_runs(self) -> None:
        """Hydrate the in-memory cache from persisted runs at startup."""
        try:
            run_files = list(self.base_dir.glob("*/run.json"))
            for run_file in sorted(run_files):
                run_id = run_file.parent.name
                try:
                    content = run_file.read_text(encoding="utf-8")
                    if not content.strip():
                        continue

                    run = RunRecord.model_validate_json(content)
                    sync_logger.debug(f"Loaded run {run_id}: status {run.status}")

                    with self._registry_lock:
                        self._runs[run_id] = run

                    events_path = run_file.parent / "events.jsonl"
                    if events_path.exists():
                        events = [
                            RunEvent.model_validate_json(line)
                            for line in events_path.read_text(encoding="utf-8").splitlines()
                            if line.strip()
                        ]
                        with self._registry_lock:
                            self._events_cache[run_id] = events
                except (OSError, ValidationError, json.JSONDecodeError, KeyError) as e:
                    sync_logger.error(f"Failed to load {run_id}: {e}")
                    continue
        except OSError as e:
            sync_logger.error(f"Load error: {e}")
            pass

    async def create_run(self, record: RunRecord | None = None) -> RunRecord:
        if record is None:
            raise ValueError("create_run requires a RunRecord")
        with self._registry_lock:
            self._runs[record.id] = record
        await self.persist_run(record.id)
        return record

    def new_run_id(self) -> str:
        return uuid4().hex

    def run_dir(self, run_id: str) -> Path:
        return ensure_dir(self.base_dir / run_id)

    def node_artifact_dir(self, run_id: str, node_id: str) -> Path:
        return ensure_dir(self.run_dir(run_id) / "artifacts" / node_id)

    def artifact_path(self, run_id: str, node_id: str, name: str) -> Path:
        return self.node_artifact_dir(run_id, node_id) / name

    def cancel_request_path(self, run_id: str) -> Path:
        return self.run_dir(run_id) / "cancel.requested"

    async def persist_run(self, run_id: str) -> None:
        await asyncio.to_thread(self._persist_run_sync, run_id)

    def _persist_run_sync(self, run_id: str) -> None:
        lock = self._locks[run_id]
        with lock:
            with self._registry_lock:
                record = self._runs[run_id]
                payload = record.model_dump_json(indent=2)
            path = self.run_dir(run_id) / "run.json"
            path.write_text(payload, encoding="utf-8")

    async def append_event(self, run_id: str, event: RunEvent) -> None:
        await asyncio.to_thread(self._append_event_sync, run_id, event)
        with self._registry_lock:
            subscribers = list(self._subscribers[run_id])
        for subscriber in subscribers:
            subscriber.put_nowait(event)

    def _append_event_sync(self, run_id: str, event: RunEvent) -> None:
        lock = self._locks[run_id]
        with lock:
            run_dir = self.run_dir(run_id)
            with (run_dir / "events.jsonl").open("a", encoding="utf-8") as handle:
                handle.write(event.model_dump_json())
                handle.write("\n")
            with self._registry_lock:
                self._events_cache[run_id].append(event)

    async def request_cancel(self, run_id: str) -> None:
        await asyncio.to_thread(self._request_cancel_sync, run_id)

    def _request_cancel_sync(self, run_id: str) -> None:
        lock = self._locks[run_id]
        with lock:
            self.cancel_request_path(run_id).write_text("cancel\n", encoding="utf-8")

    def cancel_requested(self, run_id: str) -> bool:
        return self.cancel_request_path(run_id).exists()

    async def clear_cancel_request(self, run_id: str) -> None:
        await asyncio.to_thread(self._clear_cancel_request_sync, run_id)

    def _clear_cancel_request_sync(self, run_id: str) -> None:
        lock = self._locks[run_id]
        with lock:
            self.cancel_request_path(run_id).unlink(missing_ok=True)

    async def append_artifact_text(self, run_id: str, node_id: str, name: str, content: str) -> None:
        await asyncio.to_thread(self._append_artifact_text_sync, run_id, node_id, name, content)

    def _append_artifact_text_sync(self, run_id: str, node_id: str, name: str, content: str) -> None:
        path = self.artifact_path(run_id, node_id, name)
        lock = self._locks[run_id]
        with lock:
            with path.open("a", encoding="utf-8") as handle:
                handle.write(content)

    async def write_artifact_text(self, run_id: str, node_id: str, name: str, content: str) -> None:
        await asyncio.to_thread(self._write_artifact_text_sync, run_id, node_id, name, content)

    def _write_artifact_text_sync(self, run_id: str, node_id: str, name: str, content: str) -> None:
        path = self.artifact_path(run_id, node_id, name)
        lock = self._locks[run_id]
        with lock:
            path.write_text(content, encoding="utf-8")

    async def write_artifact_json(self, run_id: str, node_id: str, name: str, payload: object) -> None:
        await self.write_artifact_text(run_id, node_id, name, json.dumps(payload, ensure_ascii=False, indent=2))

    def read_artifact_text(self, run_id: str, node_id: str, name: str) -> str:
        return self.artifact_path(run_id, node_id, name).read_text(encoding="utf-8")

    def get_run(self, run_id: str) -> RunRecord:
        with self._registry_lock:
            return self._runs[run_id]

    def list_runs(self) -> list[RunRecord]:
        with self._registry_lock:
            runs = list(self._runs.values())
        return sorted(runs, key=lambda run: run.created_at, reverse=True)

    def get_events(self, run_id: str) -> list[RunEvent]:
        with self._registry_lock:
            return list(self._events_cache[run_id])

    async def subscribe(self, run_id: str) -> queue.Queue[RunEvent]:
        subscriber: queue.Queue[RunEvent] = queue.Queue()
        with self._registry_lock:
            self._subscribers[run_id].add(subscriber)
        return subscriber

    async def unsubscribe(self, run_id: str, subscriber: queue.Queue[RunEvent]) -> None:
        with self._registry_lock:
            self._subscribers[run_id].discard(subscriber)
