"""Parallel Gaia proposal and critique flow across multiple branches."""

from agentflow import Graph, gaia


with Graph("multi-agent-debate") as dag:
    proposal_a = gaia(
        task_id="proposal_a",
        prompt="Propose a solution to improve error handling in the codebase.",
    )
    proposal_b = gaia(
        task_id="proposal_b",
        prompt="Independently propose a solution to improve error handling in the codebase.",
    )
    critique_a = gaia(
        task_id="critique_a",
        prompt=(
            "Review proposal B and identify strengths, weaknesses, "
            "risks, and concrete improvements.\n\n"
            "{{ nodes.proposal_b.output }}"
        ),
    )
    critique_b = gaia(
        task_id="critique_b",
        prompt=(
            "Review proposal A and identify strengths, weaknesses, "
            "risks, and concrete improvements.\n\n"
            "{{ nodes.proposal_a.output }}"
        ),
    )
    synthesis = gaia(
        task_id="synthesis",
        prompt=(
            "Synthesize the best ideas from both solutions and both critiques into "
            "one final recommendation.\n\n"
            "Proposal A:\n{{ nodes.proposal_a.output }}\n\n"
            "Proposal B:\n{{ nodes.proposal_b.output }}\n\n"
            "Critique A:\n{{ nodes.critique_a.output }}\n\n"
            "Critique B:\n{{ nodes.critique_b.output }}"
        ),
    )

    proposal_a >> [critique_a, critique_b]
    proposal_b >> [critique_a, critique_b]
    [critique_a, critique_b] >> synthesis

if __name__ == "__main__":
    print(dag.to_json())
