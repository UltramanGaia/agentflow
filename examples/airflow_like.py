"""Smallest Python-authored Codex/Claude DAG reference."""

from agentflow import Graph, claude, codex


with Graph("airflow-like-example", working_dir=".", concurrency=3) as dag:
    plan = codex(
        task_id="plan",
        prompt="Inspect the repo and produce a concise plan.",
        model="gpt-5-codex",
        tools="read_only",
    )
    implement = claude(
        task_id="implement",
        prompt="Implement the approved plan:\n\n{{ nodes.plan.output }}",
        model="claude-sonnet-4-5",
        tools="read_write",
    )
    review = codex(
        task_id="review",
        prompt="Review the plan and call out risks:\n\n{{ nodes.plan.output }}",
        capture="trace",
        tools="read_only",
    )
    merge = codex(
        task_id="merge",
        prompt=(
            "Merge the implementation and review into one final response.\n\n"
            "Implementation:\n{{ nodes.implement.output }}\n\n"
            "Review:\n{{ nodes.review.output }}"
        ),
        model="gpt-5-codex",
    )

    plan >> [implement, review]
    [implement, review] >> merge

print(dag.to_json())
