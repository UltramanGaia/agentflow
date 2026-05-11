#!/usr/bin/env bash
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_ROOT"

for cmd in python cargo rustc; do
  if ! command -v "$cmd" >/dev/null 2>&1; then
    echo "missing required command: $cmd" >&2
    exit 1
  fi
done

echo "== tests =="
python -m pytest tests/test_agents.py tests/test_tuned_agents.py -q

echo
echo "== tuned agents =="
python -m agentflow tuned-agents

echo
echo "== tuned agent detail =="
python -m agentflow tuned-agent gaia_tuned --output json

TMP_PIPELINE="$(mktemp --suffix=.py)"
trap 'rm -f "$TMP_PIPELINE"' EXIT

cat >"$TMP_PIPELINE" <<PY
from pathlib import Path

from agentflow import Graph, agent

WORKSPACE = Path(${REPO_ROOT@Q})

with Graph("verify-tuned-agent", working_dir=str(WORKSPACE)) as g:
    agent("gaia_tuned", task_id="verify", prompt="Reply with exactly READY.")

print(g.to_json())
PY

echo
echo "== inspect tuned pipeline =="
python -m agentflow inspect "$TMP_PIPELINE" --output summary

echo
echo "== run tuned pipeline =="
python -m agentflow run "$TMP_PIPELINE" --output summary
