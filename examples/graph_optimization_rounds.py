"""Loader-consumable example that prints only pipeline JSON when executed.

`load_pipeline_from_path()` executes Python examples from the example directory,
so we prepend the repo root when needed to keep this loader-consumable in a
repo checkout without relying on an editable installation.
"""

from pathlib import Path
import sys

repo_root = Path(__file__).resolve().parents[1]
if str(repo_root) not in sys.path:
    sys.path.insert(0, str(repo_root))

from agentflow import Graph, codex

optimizer = "codex"  # agent used to patch the graph between rounds
n_run = 2  # total optimization rounds

with Graph("graph-optimization-rounds", optimizer=optimizer, n_run=n_run, concurrency=2) as g:
    plan = codex(
        task_id="plan",
        prompt="Draft a short implementation plan.",
        repo_instructions_mode="ignore",
    )
    review = codex(
        task_id="review",
        prompt="Review the plan for gaps and missing steps.",
        repo_instructions_mode="ignore",
    )
    summary = codex(
        task_id="summary",
        prompt="Summarize the approved plan and next actions.",
        repo_instructions_mode="ignore",
    )

    plan >> review >> summary

if __name__ == "__main__":
    print(g.to_json())
