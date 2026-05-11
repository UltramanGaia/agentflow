"""Static large-scale Gaia repository sweep with count fanout and batched reducers."""

from agentflow import Graph, fanout, gaia, merge


with Graph(
    "gaia-repo-sweep-batched-128",
    description="Static 128-shard Gaia repository sweep with batched reducers for maintainer review.",
    working_dir="./codex_repo_sweep_batched_128",
    concurrency=32,
    node_defaults={
        "agent": "gaia",
        "tools": "read_only",
        "capture": "final",
        "timeout_seconds": 900,
    },
    agent_defaults={
        "gaia": {
            "model": "gpt-5.4",
            "retries": 1,
            "retry_backoff_seconds": 1,
            "extra_args": ["--search", "-c", 'model_reasoning_effort="high"'],
        }
    },
) as dag:
    prepare = gaia(
        task_id="prepare",
        prompt=(
            "Inspect the repository and write shared instructions for a 128-shard Gaia maintainer sweep.\n"
            "\n"
            "Review goal:\n"
            "- Focus on bugs, risky code paths, and missing tests.\n"
            "- Prefer concrete bugs, risky assumptions, or clearly missing tests over generic style feedback.\n"
            "- Make the sweep reproducible by using a stable path-hash modulo strategy across 128 shards.\n"
            "- Call out hot subsystems or directories that deserve extra attention.\n"
            "- End with a compact rubric the reducers can use to rank findings by severity and confidence.\n"
        ),
    )

    sweep = fanout(
        gaia(
            task_id="sweep",
            prompt=(
                "You are Gaia repository sweep shard {{ item.number }} of {{ item.count }}.\n"
                "\n"
                "Shared plan:\n"
                "{{ nodes.prepare.output }}\n"
                "\n"
                "Your shard contract:\n"
                "- Stable identity: {{ item.node_id }} (suffix {{ item.suffix }})\n"
                "- Review files whose stable path hash modulo {{ item.count }} equals {{ item.index }}.\n"
                "- Focus on bugs, risky code paths, and missing tests.\n"
                "- Avoid duplicate work outside your modulo slice unless you need one small neighboring file for context.\n"
                "- Report concrete findings first. Include file paths, the failure mode, and the missing validation or test if applicable.\n"
                "- If your slice is quiet, report the most suspicious code paths worth a second pass.\n"
            ),
        ),
        128,
        derive={"label": "slice {{ item.number }}/{{ item.count }}"},
    )

    batch_merge = merge(
        gaia(
            task_id="batch_merge",
            prompt=(
                "Prepare the maintainer handoff for review batch {{ item.number }} of {{ item.count }}.\n"
                "\n"
                "Batch coverage:\n"
                "- Source group: {{ item.source_group }}\n"
                "- Total source shards: {{ item.source_count }}\n"
                "- Batch size: {{ item.scope.size }}\n"
                "- Shard range: {{ item.start_number }} through {{ item.end_number }}\n"
                '- Shard ids: {{ item.scope.ids | join(", ") }}\n'
                "- Completed shards: {{ item.scope.summary.completed }}\n"
                "- Failed shards: {{ item.scope.summary.failed }}\n"
                "- Silent shards: {{ item.scope.summary.without_output }}\n"
                "\n"
                "Rank the batch findings by severity, then confidence, then breadth of impact. "
                "If the batch is quiet, say so explicitly and point to the slices that should be rerun or retargeted.\n"
                "\n"
                "{% for shard in item.scope.with_output.nodes %}\n"
                "## {{ shard.label }} :: {{ shard.node_id }} (status: {{ shard.status }})\n"
                "{{ shard.output }}\n"
                "\n"
                "{% endfor %}"
                "{% if item.scope.failed.size %}\n"
                "Failed slices:\n"
                "{% for shard in item.scope.failed.nodes %}\n"
                "- {{ shard.id }} :: {{ shard.label }}\n"
                "{% endfor %}"
                "{% endif %}"
                "{% if not item.scope.with_output.size %}\n"
                "No slice in this batch produced reducer-ready output. "
                "Say that explicitly and use the failed shard list to suggest retargeting.\n"
                "{% endif %}"
            ),
        ),
        sweep,
        size=16,
    )

    final = gaia(
        task_id="merge",
        prompt=(
            "Consolidate this 128-shard repository sweep into a maintainer summary.\n"
            "Start with the highest-risk findings, then repeated patterns across batches, "
            "and end with quiet or failed slices that need a follow-up pass.\n"
            "\n"
            "Campaign status:\n"
            "- Total review shards: {{ fanouts.sweep.size }}\n"
            "- Completed shards: {{ fanouts.sweep.summary.completed }}\n"
            "- Failed shards: {{ fanouts.sweep.summary.failed }}\n"
            "- Silent shards: {{ fanouts.sweep.summary.without_output }}\n"
            "- Batch reducers completed: {{ fanouts.batch_merge.summary.completed }} / {{ fanouts.batch_merge.size }}\n"
            "\n"
            "{% for batch in fanouts.batch_merge.with_output.nodes %}\n"
            "## Batch {{ batch.number }} :: shards {{ batch.start_number }}-{{ batch.end_number }} (status: {{ batch.status }})\n"
            "{{ batch.output }}\n"
            "\n"
            "{% endfor %}"
            "{% if fanouts.batch_merge.without_output.size %}\n"
            "Batch reducers needing attention:\n"
            "{% for batch in fanouts.batch_merge.without_output.nodes %}\n"
            "- {{ batch.id }} :: shards {{ batch.start_number }}-{{ batch.end_number }} (status: {{ batch.status }})\n"
            "{% endfor %}"
            "{% endif %}"
        ),
    )

    prepare >> sweep
    sweep >> batch_merge
    batch_merge >> final

if __name__ == "__main__":
    print(dag.to_json())
