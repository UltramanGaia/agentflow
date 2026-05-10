"""Parallel proposal and critique flow across multiple agents."""

from agentflow import Graph, claude, codex


with Graph("multi-agent-debate") as dag:
    codex_solve = codex(
        task_id="codex_solve",
        prompt="Propose a solution to improve error handling in the codebase.",
    )
    claude_solve = claude(
        task_id="claude_solve",
        prompt="Independently propose a solution to improve error handling in the codebase.",
    )
    codex_critique = codex(
        task_id="codex_critique",
        prompt=(
            "Review Claude's proposed solution and identify strengths, weaknesses, "
            "risks, and concrete improvements.\n\n"
            "{{ nodes.claude_solve.output }}"
        ),
    )
    claude_critique = claude(
        task_id="claude_critique",
        prompt=(
            "Review Codex's proposed solution and identify strengths, weaknesses, "
            "risks, and concrete improvements.\n\n"
            "{{ nodes.codex_solve.output }}"
        ),
    )
    synthesis = claude(
        task_id="synthesis",
        prompt=(
            "Synthesize the best ideas from both solutions and both critiques into "
            "one final recommendation.\n\n"
            "Codex solution:\n{{ nodes.codex_solve.output }}\n\n"
            "Claude solution:\n{{ nodes.claude_solve.output }}\n\n"
            "Codex critique:\n{{ nodes.codex_critique.output }}\n\n"
            "Claude critique:\n{{ nodes.claude_critique.output }}"
        ),
    )

    codex_solve >> [codex_critique, claude_critique]
    claude_solve >> [codex_critique, claude_critique]
    [codex_critique, claude_critique] >> synthesis

print(dag.to_json())
