# Examples Guide

`examples/` is the canonical reference set for starter pipelines.

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
| `code_review.py` | You need independent multi-file code review. | Fan out review across files, merge findings. |
| `dep_audit.py` | You need to audit dependencies for security/license issues. | Static list fanout with executive summary. |
| `test_gap.py` | You want to find untested modules and suggest targeted tests. | Analysis fanout across risky modules. |
| `multi_agent_debate.py` | You want parallel proposal and critique flow across multiple agents. | Codex vs Claude: independent solve + cross-critique. |
| `release_check.py` | You need a parallel release gate. | Tests + security + changelog in parallel → go/no-go decision. |
| `iterative_impl.py` | You want a write → review → fix cycle until LGTM. | `on_failure` loop until success criteria met. |
| `pi_local_lmstudio.py` | You want local LLMs for scanning, external agents for synthesis. | Pi agent with local LMStudio, Codex for final review. |
| `graph_optimization_rounds.py` | You want multiple optimization rounds over your graph. | `optimizer` + `n_run` for graph rewriting between rounds. |
| `airflow_like_fuzz_batched.py` | You want a large shard campaign driven by count fanout, batch merge, and periodic monitor. | `fanout(node, 128)`, `merge(node, src, size=16)`, `schedule.every_seconds`. |
| `airflow_like_fuzz_grouped.py` | You want a large shard campaign driven by matrix fanout and grouped merge. | `fanout(node, {...})`, `merge(node, src, by=[...])`. |
| `repo_sweep_batched.py` | You want a large repository review that still produces a readable maintainer handoff. | `fanout`, `merge`, `node_defaults`, `agent_defaults`, staged reducers. |
