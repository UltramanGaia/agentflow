"""Independent multi-file Gaia review with fanout and final synthesis."""

from agentflow import Graph, fanout, gaia


with Graph("code-review-example", working_dir=".", concurrency=6) as dag:
    scan = gaia(
        task_id="scan",
        prompt=(
            "Scan the repository and list the top 5 most important files to review.\n"
            "Return a ranked list with a short reason for each file."
        ),
        tools="read_only",
    )

    review = fanout(
        gaia(
            task_id="review",
            prompt=(
                "Review {{ item.file }} independently.\n\n"
                "Repository scan:\n"
                "{{ nodes.scan.output }}\n\n"
                "Focus on the most important bugs, risks, regressions, and missing tests in this file.\n"
                "Keep the review concise and prioritized."
            ),
            tools="read_only",
        ),
        [
            {"file": "agentflow/dsl.py"},
            {"file": "agentflow/orchestrator.py"},
            {"file": "agentflow/context.py"},
            {"file": "agentflow/specs.py"},
            {"file": "agentflow/cli.py"},
        ],
    )

    merge = gaia(
        task_id="merge",
        prompt=(
            "Merge these code review findings into a prioritized summary.\n\n"
            "Repository scan:\n"
            "{{ nodes.scan.output }}\n\n"
            "{% for r in fanouts.review.nodes %}\n"
            "## {{ r.file }}\n"
            "{{ r.output }}\n\n"
            "{% endfor %}"
            "Produce a final summary ordered by severity, then note any cross-file themes."
        ),
    )

    scan >> review
    [scan, review] >> merge

if __name__ == "__main__":
    print(dag.to_json())
