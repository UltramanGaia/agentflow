"""Multi-round graph optimization with Gaia as the optimizer agent."""

from agentflow import Graph, gaia

optimizer = "gaia"  # agent used to patch the graph between rounds
n_run = 2  # total optimization rounds

with Graph("graph-optimization-rounds", optimizer=optimizer, n_run=n_run, concurrency=2) as dag:
    plan = gaia(
        task_id="plan",
        prompt="Draft a short implementation plan.",
        repo_instructions_mode="ignore",
    )
    review = gaia(
        task_id="review",
        prompt="Review the plan for gaps and missing steps.",
        repo_instructions_mode="ignore",
    )
    summary = gaia(
        task_id="summary",
        prompt="Summarize the approved plan and next actions.",
        repo_instructions_mode="ignore",
    )

    plan >> review >> summary

if __name__ == "__main__":
    print(dag.to_json())
