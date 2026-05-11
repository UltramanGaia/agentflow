"""Gaia scan example with parallel file review and merged synthesis."""

from agentflow import Graph, fanout, gaia, merge


with Graph("gaia-parallel-scan", working_dir=".", concurrency=4) as dag:
    scans = fanout(
        gaia(
            task_id="scan",
            prompt=(
                "Read {{ item.path }} and extract every TODO/FIXME/HACK with 1 line "
                "of context. If none, reply with 'NONE'."
            ),
            tools="read_only",
        ),
        [
            {"path": "agentflow/dsl.py"},
            {"path": "agentflow/orchestrator.py"},
            {"path": "agentflow/specs.py"},
            {"path": "agentflow/traces.py"},
        ],
    )

    summary = merge(
        gaia(
            task_id="summary",
            prompt=(
                "Consolidate these scan results into a single punch list, grouped by urgency.\n\n"
                "{% for r in fanouts.scan.nodes %}{{ r.output }}\n---\n{% endfor %}"
            ),
        ),
        scans,
        size=4,
    )


if __name__ == "__main__":
    print(dag.to_json())
