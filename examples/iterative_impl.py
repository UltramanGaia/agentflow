"""Iterative implementation loop that rewrites based on review feedback."""

from agentflow import Graph, gaia

with Graph("iterative-implementation", max_iterations=5) as dag:
    write = gaia(
        task_id="write",
        prompt=(
            "You are implementing a Python function that validates email addresses.\n"
            "Requirements: handle edge cases, return bool, include docstring.\n\n"
            "{% if nodes.review.output %}\n"
            "Previous review feedback:\n"
            "{{ nodes.review.output }}\n\n"
            "Fix ALL issues listed above.\n"
            "{% else %}\n"
            "This is the first attempt. Write the initial implementation.\n"
            "{% endif %}"
        ),
        tools="read_write",
    )
    review = gaia(
        task_id="review",
        prompt=(
            "Review this implementation for correctness and completeness.\n\n"
            "{{ nodes.write.output }}\n\n"
            "If the implementation is complete and correct, respond with exactly: LGTM\n"
            "Otherwise, list specific issues that must be fixed."
        ),
        success_criteria=[{"kind": "output_contains", "value": "LGTM"}],
    )
    summary = gaia(
        task_id="summary",
        prompt=(
            "Summarize the iterative implementation process.\n"
            "Final code:\n{{ nodes.write.output }}\n"
            "Final review:\n{{ nodes.review.output }}"
        ),
    )

    write >> review
    review.on_failure >> write  # loop until LGTM
    review >> summary           # proceed to summary on success

if __name__ == "__main__":
    print(dag.to_json())
