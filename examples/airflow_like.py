"""Smallest Python-authored Gaia pipeline reference."""

from agentflow import Graph, gaia


with Graph("airflow-like-example", working_dir=".", concurrency=3) as dag:
    plan = gaia(
        task_id="plan",
        prompt="Inspect the repo and produce a concise plan.",
        tools="read_only",
    )
    implement = gaia(
        task_id="implement",
        prompt="Implement the approved plan:\n\n{{ nodes.plan.output }}",
        tools="read_write",
    )
    review = gaia(
        task_id="review",
        prompt="Review the plan and call out risks:\n\n{{ nodes.plan.output }}",
        capture="trace",
        tools="read_only",
    )
    merge = gaia(
        task_id="merge",
        prompt=(
            "Merge the implementation and review into one final response.\n\n"
            "Implementation:\n{{ nodes.implement.output }}\n\n"
            "Review:\n{{ nodes.review.output }}"
        ),
    )

    plan >> [implement, review]
    [implement, review] >> merge

if __name__ == "__main__":
    print(dag.to_json())
