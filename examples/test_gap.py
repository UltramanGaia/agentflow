from agentflow import Graph, codex, claude, fanout


with Graph("test-gap-analysis", working_dir=".", concurrency=6) as dag:
    analyze = codex(
        task_id="analyze",
        prompt=(
            "Inspect the repository and identify source modules with missing or weak test coverage.\n"
            "Focus on risky logic, edge cases, integration seams, and regression-prone behavior.\n"
            "Summarize the highest-value coverage gaps and why they matter."
        ),
    )

    suggest = fanout(
        codex(
            task_id="suggest",
            prompt=(
                "You are generating targeted test ideas for {{ item.module }}.\n\n"
                "Shared repo coverage analysis:\n"
                "{{ nodes.analyze.output }}\n\n"
                "Review {{ item.module }} and propose concrete tests that would close the most important gaps.\n"
                "Prioritize edge cases, failure modes, state transitions, and integration boundaries.\n"
                "For each idea, explain what behavior it validates and why it is high value."
            ),
        ),
        [
            {"module": "agentflow/orchestrator.py"},
            {"module": "agentflow/specs.py"},
            {"module": "agentflow/context.py"},
            {"module": "agentflow/runner.py"},
        ],
    )

    prioritize = claude(
        task_id="prioritize",
        prompt=(
            "Prioritize the proposed tests by risk and impact.\n\n"
            "Shared repo analysis:\n"
            "{{ nodes.analyze.output }}\n\n"
            "Module-specific suggestions:\n"
            "{% for suggestion in fanouts.suggest.with_output.nodes %}\n"
            "## {{ suggestion.module }}\n"
            "{{ suggestion.output }}\n\n"
            "{% endfor %}"
            "Produce a ranked shortlist with the highest-risk, highest-impact tests first.\n"
            "Call out which tests should be written immediately and which can wait."
        ),
    )

    analyze >> suggest
    [analyze, suggest] >> prioritize

print(dag.to_json())
