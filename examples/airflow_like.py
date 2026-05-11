"""Smallest Python-authored Pi DAG reference."""

from agentflow import Graph, pi


with Graph("airflow-like-example", working_dir=".", concurrency=3) as dag:
    plan = pi(
        task_id="plan",
        prompt="Inspect the repo and produce a concise plan.",
        tools="read_only",
    )
    implement = pi(
        task_id="implement",
        prompt="Implement the approved plan:\n\n{{ nodes.plan.output }}",
        tools="read_write",
    )
    review = pi(
        task_id="review",
        prompt="Review the plan and call out risks:\n\n{{ nodes.plan.output }}",
        capture="trace",
        tools="read_only",
    )
    merge = pi(
        task_id="merge",
        prompt=(
            "Merge the implementation and review into one final response.\n\n"
            "Implementation:\n{{ nodes.implement.output }}\n\n"
            "Review:\n{{ nodes.review.output }}"
        ),
    )

    plan >> [implement, review]
    [implement, review] >> merge

print(dag.to_json())
