from __future__ import annotations

import asyncio
from pathlib import Path

from agentflow.scratchboard import SCRATCHBOARD_FILENAME
from agentflow.scratchboard_manager import ScratchboardManager


def test_scratchboard_manager_creates_prompt_suffix(tmp_path: Path) -> None:
    manager = ScratchboardManager()

    manager.create_for_run(tmp_path, "run")
    suffix = manager.prompt_suffix_for_run("run")

    assert str(tmp_path / "run" / SCRATCHBOARD_FILENAME) in suffix
    assert manager.prompt_suffix_for_run("missing") == ""


def test_scratchboard_manager_merges_prefixed_output(tmp_path: Path) -> None:
    manager = ScratchboardManager()
    scratchboard = manager.create_for_run(tmp_path, "run")

    asyncio.run(
        manager.merge_output(
            "run",
            "node",
            "ignored\nSCRATCHBOARD: important finding\nSCRATCHBOARD: another finding",
        )
    )

    text = scratchboard.read()
    assert "important finding" in text
    assert "another finding" in text
    assert "ignored" not in text


def test_scratchboard_manager_clear_run_removes_prompt_suffix(tmp_path: Path) -> None:
    manager = ScratchboardManager()
    manager.create_for_run(tmp_path, "run")

    manager.clear_run("run")

    assert manager.prompt_suffix_for_run("run") == ""
