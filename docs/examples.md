# Examples Guide

`examples/` is the single source of truth for starter pipelines.

Use:

```bash
agentflow examples
cp examples/airflow_like.py pipeline.py
```

The intended workflow is simple: read an example, copy it, then edit it into your own pipeline.

## Python Examples

| Example | Use it when | Key features |
| --- | --- | --- |
| `airflow_like.py` | You want the smallest Python-authored DAG reference. | Static dependencies with `plan >> [implement, review]`. |
| `airflow_like_fuzz_batched.py` | You want a large shard campaign driven by count fanout, batch merge, and a periodic monitor. | `fanout(node, 128)`, `merge(node, src, size=16)`, `schedule.every_seconds`. |
| `airflow_like_fuzz_grouped.py` | You want a large shard campaign driven by matrix fanout and grouped merge. | `fanout(node, {...})`, `merge(node, src, by=[...])`. |
| `repo_sweep_batched.py` | You want a large repository review that still produces a readable maintainer handoff. | `fanout`, `merge`, `node_defaults`, `agent_defaults`, staged reducers. |
