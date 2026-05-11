#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

if [[ -x ".venv/bin/python" ]]; then
  PYTHON=".venv/bin/python"
else
  PYTHON="python3"
fi

latest_parent_run() {
  "$PYTHON" - <<'PY'
import json
from pathlib import Path

candidates = []
for path in Path(".agentflow/runs").glob("*"):
    run_json = path / "run.json"
    if not run_json.exists():
        continue
    data = json.loads(run_json.read_text())
    pipeline = data.get("pipeline", {})
    if data.get("optimization_parent_run_id") is None and pipeline.get("optimizer") == "gaia" and pipeline.get("n_run") == 2:
        candidates.append((path.stat().st_mtime, path))

print(candidates and str(sorted(candidates)[-1][1]) or "")
PY
}

before_latest="$(latest_parent_run)"

"$PYTHON" -m agentflow run examples/graph_optimization_rounds.py --output summary

after_latest="$(latest_parent_run)"
if [[ -z "$after_latest" || "$after_latest" == "$before_latest" ]]; then
  echo "failed to detect a new run directory" >&2
  exit 1
fi

round_dir="$after_latest/optimization/round-001"
round_two_dir="$after_latest/optimization/round-002"

for path in \
  "$round_dir/pipeline.original.py" \
  "$round_dir/pipeline.edited.py" \
  "$round_dir/graph_report.json" \
  "$round_dir/optimizer-prompt.txt" \
  "$round_dir/optimizer-result.json" \
  "$round_dir/optimizer-validation.json" \
  "$round_two_dir/pipeline.original.py" \
  "$round_two_dir/pipeline.py" \
  "$round_two_dir/graph_report.json"
do
  if [[ ! -f "$path" ]]; then
    echo "missing expected artifact: $path" >&2
    exit 1
  fi
done

echo "graph optimization smoke run passed"
echo "run_dir=$after_latest"
