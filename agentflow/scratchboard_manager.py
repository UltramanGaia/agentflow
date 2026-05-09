from __future__ import annotations

import threading
from pathlib import Path

from agentflow.scratchboard import SCRATCHBOARD_FILENAME, SCRATCHBOARD_PROMPT_SUFFIX, Scratchboard


class ScratchboardManager:
    def __init__(self) -> None:
        self._scratchboards: dict[str, Scratchboard] = {}
        self._lock = threading.RLock()

    def create_for_run(self, base_dir: Path, run_id: str) -> Scratchboard:
        scratchboard = Scratchboard(base_dir / run_id / SCRATCHBOARD_FILENAME)
        with self._lock:
            self._scratchboards[run_id] = scratchboard
        return scratchboard

    def prompt_suffix_for_run(self, run_id: str) -> str:
        with self._lock:
            scratchboard = self._scratchboards.get(run_id)
        if scratchboard is None:
            return ""
        return SCRATCHBOARD_PROMPT_SUFFIX.format(scratchboard_path=str(scratchboard.path))

    async def merge_output(self, run_id: str, node_id: str, output: str | None) -> None:
        if not output:
            return
        with self._lock:
            scratchboard = self._scratchboards.get(run_id)
        if scratchboard is None:
            return
        for line in output.splitlines():
            stripped = line.strip()
            if stripped.startswith("SCRATCHBOARD:"):
                content = stripped.removeprefix("SCRATCHBOARD:").strip()
                await scratchboard.append(node_id, content)

    def clear_run(self, run_id: str) -> None:
        with self._lock:
            self._scratchboards.pop(run_id, None)
