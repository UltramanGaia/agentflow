from __future__ import annotations

import asyncio
import json
import queue
from collections.abc import AsyncIterator

from agentflow.store import RunStore


def _encode_sse(event: str, payload: dict) -> bytes:
    body = json.dumps(payload, ensure_ascii=False)
    return f"event: {event}\ndata: {body}\n\n".encode("utf-8")


async def stream_run_events(store: RunStore, run_id: str) -> AsyncIterator[bytes]:
    subscriber = await store.subscribe(run_id)
    try:
        history = [event.model_dump(mode="json") for event in store.get_events(run_id)]
        yield _encode_sse("snapshot", {"events": history})
        while True:
            try:
                event = await asyncio.to_thread(subscriber.get, True, 1.0)
            except queue.Empty:
                yield b": heartbeat\n\n"
                continue
            yield _encode_sse("event", event.model_dump(mode="json"))
    finally:
        await store.unsubscribe(run_id, subscriber)
