from __future__ import annotations

import asyncio
import json
import sys
from datetime import datetime
from typing import TYPE_CHECKING, Any
try:
    from enum import StrEnum
except ImportError:  # pragma: no cover - Python < 3.11
    from enum import Enum

    class StrEnum(str, Enum):
        pass
from pathlib import Path

import typer
from pydantic import ValidationError
from agentflow.defaults import (
    bundled_templates,
    bundled_template_names,
    default_smoke_pipeline_path,
    render_bundled_template,
)
from agentflow.specs import (
    AgentKind,
    NodeResult,
    NodeSpec,
    NodeStatus,
    PipelineSpec,
    ProviderConfig,
    RunRecord,
    RunStatus,
    normalize_agent_name,
)
from agentflow.store import RunStore
from agentflow.tuned_agents import (
    TunedAgentRecord,
    list_tuned_agent_records,
    resolve_tuned_agent_version,
    run_evolution_from_payload,
)

if TYPE_CHECKING:
    from agentflow.orchestrator import Orchestrator

app = typer.Typer(add_completion=False)


class OutputFormat(StrEnum):
    AUTO = "auto"
    JSON = "json"
    JSON_SUMMARY = "json-summary"
    SUMMARY = "summary"


def _build_runtime(runs_dir: str, max_concurrent_runs: int) -> tuple[RunStore, Orchestrator]:
    from agentflow.orchestrator import Orchestrator

    store = RunStore(runs_dir)
    orchestrator = Orchestrator(store=store, max_concurrent_runs=max_concurrent_runs)
    return store, orchestrator


def _build_store(runs_dir: str) -> RunStore:
    return RunStore(runs_dir)


def _render_tuned_agents_summary(records: list[TunedAgentRecord]) -> str:
    if not records:
        return "No tuned agents found."
    lines: list[str] = []
    for record in records:
        lines.append(
            f"{record.name}"
            f" [{_status_value(record.base_agent)}] "
            f"latest={record.latest_version or '-'} "
            f"versions={len(record.versions)}"
        )
    return "\n".join(lines)


def _render_tuned_agent_detail(record: TunedAgentRecord | None) -> str:
    if record is None:
        return "Tuned agent not found."
    lines = [
        f"Name: {record.name}",
        f"Base agent: {_status_value(record.base_agent)}",
        f"Latest version: {record.latest_version or '-'}",
        f"Versions: {len(record.versions)}",
    ]
    for version in record.versions:
        lines.append(
            f" - {version.id} status={version.status} "
            f"repo={version.repo_path}"
        )
    return "\n".join(lines)


def _render_evolution_summary(result: dict[str, Any]) -> str:
    return "\n".join(
        [
            f"Agent: {result.get('agent_name', '-')}",
            f"Version: {result.get('version', '-')}",
            f"Base agent: {result.get('base_agent', '-')}",
            f"Executable: {result.get('executable', '-')}",
            f"Repo path: {result.get('repo_path', '-')}",
        ]
    )


def _load_pipeline(path: str) -> PipelineSpec:
    from agentflow.loader import load_pipeline_from_path

    try:
        return load_pipeline_from_path(path)
    except (OSError, ValidationError, ValueError, json.JSONDecodeError) as exc:
        typer.echo(f"Failed to load pipeline `{path}`:\n{exc}", err=True)
        raise typer.Exit(code=1) from exc


def _status_value(status: AgentKind | NodeStatus | RunStatus | str) -> str:
    return getattr(status, "value", str(status))


def _parse_iso8601(value: str | None) -> datetime | None:
    if not value:
        return None
    normalized = value.replace("Z", "+00:00")
    try:
        return datetime.fromisoformat(normalized)
    except ValueError:
        return None


def _format_duration(started_at: str | None, finished_at: str | None) -> str | None:
    started = _parse_iso8601(started_at)
    finished = _parse_iso8601(finished_at)
    if started is None or finished is None:
        return None
    duration_seconds = max((finished - started).total_seconds(), 0.0)
    if duration_seconds < 10:
        return f"{duration_seconds:.1f}s"
    if duration_seconds < 60:
        return f"{duration_seconds:.0f}s"
    minutes, seconds = divmod(int(duration_seconds), 60)
    return f"{minutes}m {seconds}s"


def _duration_seconds(started_at: str | None, finished_at: str | None) -> float | None:
    started = _parse_iso8601(started_at)
    finished = _parse_iso8601(finished_at)
    if started is None or finished is None:
        return None
    return max((finished - started).total_seconds(), 0.0)


def _preview_text(text: str | None, *, limit: int = 100) -> str | None:
    if text is None:
        return None
    collapsed = " ".join(text.split())
    if not collapsed:
        return None
    if len(collapsed) <= limit:
        return collapsed
    return collapsed[: limit - 1].rstrip() + "…"


def _node_attempt_count(node: NodeResult) -> int:
    attempts = node.attempts or []
    return len(attempts)


def _provider_name(value: str | ProviderConfig | None) -> str | None:
    if value is None:
        return None
    if isinstance(value, str):
        return value
    return value.name or None


def _pipeline_node_map(record: RunRecord) -> dict[str, NodeSpec]:
    return {node.id: node for node in record.pipeline.nodes}


def _node_identity(node_id: str, pipeline_node: NodeSpec | None) -> str:
    if pipeline_node is None:
        return node_id

    parts: list[str] = []
    parts.append(_status_value(pipeline_node.agent))

    if pipeline_node.model:
        parts.append(f"model={pipeline_node.model}")

    provider = _provider_name(pipeline_node.provider)
    if provider:
        parts.append(f"provider={provider}")

    return f"{node_id} [{', '.join(parts)}]"


def _read_node_artifact_lines(artifact_dir: Path | None, name: str) -> list[str]:
    if artifact_dir is None:
        return []
    try:
        return (artifact_dir / name).read_text(encoding="utf-8").splitlines()
    except OSError:
        return []


def _node_artifact_dir(run_dir: Path | str | None, node_id: str) -> Path | None:
    if run_dir is None:
        return None
    return Path(run_dir) / "artifacts" / node_id


def _node_text_candidates(node: NodeResult, artifact_dir: Path | None = None) -> list[str]:
    candidates: list[str] = []
    for value in (node.final_response, node.output):
        if isinstance(value, str) and value.strip():
            candidates.append(value)
    for stream_name in ("stderr.log", "stdout.log"):
        for line in _read_node_artifact_lines(artifact_dir, stream_name):
            if line.strip():
                candidates.append(line)
    return candidates


def _provider_error_subject(pipeline_node: NodeSpec | None) -> str:
    agent_name = _status_value(pipeline_node.agent).strip().lower() if pipeline_node is not None else ""

    if agent_name == "codex":
        return "Codex"
    if agent_name == "claude":
        return "Claude"
    return "The agent"


def _provider_error_diagnosis(
    node: NodeResult,
    pipeline_node: NodeSpec | None,
    artifact_dir: Path | None = None,
) -> str | None:
    combined = "\n".join(_node_text_candidates(node, artifact_dir))
    if "API Error:" not in combined:
        return None

    lowered = combined.lower()
    subject = _provider_error_subject(pipeline_node)
    if any(marker in lowered for marker in ("api error: 402", "membership", "benefits", "billing", "credits", "quota")):
        return (
            f"{subject} reached the provider, but the request was rejected with a "
            "membership/billing-style API error. The local shell bootstrap is likely working; "
            "check the upstream provider account state."
        )
    return (
        f"{subject} reached the provider, but the request was rejected upstream. "
        "The local shell bootstrap is likely working; inspect the raw API error above."
    )


def _node_preview(node: NodeResult, artifact_dir: Path | None = None) -> str | None:
    for candidate in (node.final_response, node.output):
        preview = _preview_text(candidate)
        if preview is not None:
            return preview
    stderr_lines = [line for line in _read_node_artifact_lines(artifact_dir, "stderr.log") if line.strip()]
    if stderr_lines:
        return _preview_text(stderr_lines[-1])
    return None


def _build_run_summary(record: RunRecord, run_dir: Path | str | None = None) -> dict[str, Any]:
    summary: dict[str, Any] = {
        "id": record.id,
        "status": _status_value(record.status),
        "nodes": [],
    }
    if record.pipeline.name:
        summary["pipeline"] = {"name": record.pipeline.name}
    if record.started_at:
        summary["started_at"] = record.started_at
    if record.finished_at:
        summary["finished_at"] = record.finished_at
    duration = _format_duration(record.started_at, record.finished_at)
    if duration is not None:
        summary["duration"] = duration
    duration_seconds = _duration_seconds(record.started_at, record.finished_at)
    if duration_seconds is not None:
        summary["duration_seconds"] = duration_seconds
    if run_dir is not None:
        summary["run_dir"] = str(run_dir)

    nodes: list[dict[str, Any]] = []
    pipeline_nodes = _pipeline_node_map(record)
    for node_id, node in record.nodes.items():
        pipeline_node = pipeline_nodes.get(node_id)
        artifact_dir = _node_artifact_dir(run_dir, node_id)
        node_summary: dict[str, Any] = {
            "id": node_id,
            "status": _status_value(node.status),
        }
        if pipeline_node is not None:
            node_summary["agent"] = _status_value(pipeline_node.agent)
            if pipeline_node.model:
                node_summary["model"] = pipeline_node.model
            provider = _provider_name(pipeline_node.provider)
            if provider:
                node_summary["provider"] = provider
        attempts = _node_attempt_count(node)
        if attempts:
            node_summary["attempts"] = attempts
        if node.exit_code is not None:
            node_summary["exit_code"] = node.exit_code
        preview = _node_preview(node, artifact_dir)
        if preview is not None:
            node_summary["preview"] = preview
        diagnosis = _provider_error_diagnosis(node, pipeline_node, artifact_dir)
        if diagnosis is not None:
            node_summary["diagnosis"] = diagnosis
        nodes.append(node_summary)

    summary["nodes"] = nodes
    return summary


def _render_run_summary(record: RunRecord, run_dir: Path | str | None = None) -> str:
    summary = _build_run_summary(record, run_dir=run_dir)
    lines = [f"Run {summary['id']}: {summary['status']}"]
    pipeline = summary.get("pipeline")
    if isinstance(pipeline, dict) and pipeline.get("name"):
        lines.append(f"Pipeline: {pipeline['name']}")
    duration = summary.get("duration")
    if duration is not None:
        lines.append(f"Duration: {duration}")
    run_dir_value = summary.get("run_dir")
    if run_dir_value is not None:
        lines.append(f"Run dir: {run_dir_value}")
    nodes = summary.get("nodes")
    if isinstance(nodes, list) and nodes:
        lines.append("Nodes:")
        for node in nodes:
            node_id = str(node["id"])
            parts: list[str] = []
            agent = node.get("agent")
            if agent is not None:
                parts.append(str(agent))
            model = node.get("model")
            if model:
                parts.append(f"model={model}")
            provider = node.get("provider")
            if provider:
                parts.append(f"provider={provider}")
            identity = node_id if not parts else f"{node_id} [{', '.join(parts)}]"
            rendered = f"{identity}: {node['status']}"
            metadata: list[str] = []
            attempts = node.get("attempts")
            if attempts:
                metadata.append(f"attempt {attempts}")
            exit_code = node.get("exit_code")
            if exit_code is not None:
                metadata.append(f"exit {exit_code}")
            if metadata:
                rendered += f" ({', '.join(metadata)})"
            preview = node.get("preview")
            if preview is not None:
                rendered += f" - {preview}"
            lines.append(f"- {rendered}")
            diagnosis = node.get("diagnosis")
            if diagnosis:
                lines.append(f"  Diagnosis: {diagnosis}")
    return "\n".join(lines)


def _resolve_output_format(output: OutputFormat, *, err: bool = False) -> OutputFormat:
    if output != OutputFormat.AUTO:
        return output
    if _stream_supports_tty_summary(err=err):
        return OutputFormat.SUMMARY
    return OutputFormat.JSON


def _echo_run_result(record: RunRecord, *, output: OutputFormat, run_dir: Path | str | None = None) -> None:
    resolved_output = _resolve_output_format(output)
    if resolved_output == OutputFormat.SUMMARY:
        typer.echo(_render_run_summary(record, run_dir=run_dir))
        return
    if resolved_output == OutputFormat.JSON_SUMMARY:
        typer.echo(json.dumps(_build_run_summary(record, run_dir=run_dir), indent=2))
        return
    typer.echo(json.dumps(record.model_dump(mode="json"), indent=2))


def _run_dir_for_record(store: RunStore | None, run_id: str) -> Path | str | None:
    if store is None:
        return None
    try:
        return store.run_dir(run_id)
    except (OSError, TypeError, ValueError):
        return None


def _build_runs_summary(records: list[RunRecord], *, store: RunStore | None = None) -> list[dict[str, Any]]:
    return [
        _build_run_summary(record, run_dir=_run_dir_for_record(store, record.id))
        for record in records
    ]


def _render_runs_summary(records: list[RunRecord], *, store: RunStore | None = None, total: int | None = None) -> str:
    summaries = _build_runs_summary(records, store=store)
    if not summaries:
        return "No runs found."

    visible_count = len(summaries)
    total_count = visible_count if total is None else total
    header = f"Runs: {visible_count}" if total_count == visible_count else f"Runs: {visible_count} of {total_count}"
    lines = [header]
    for summary in summaries:
        rendered = f"- {summary['id']}: {summary['status']}"
        pipeline = summary.get("pipeline")
        if isinstance(pipeline, dict) and pipeline.get("name"):
            rendered += f" - {pipeline['name']}"
        duration = summary.get("duration")
        if duration is not None:
            rendered += f" ({duration})"
        lines.append(rendered)
    return "\n".join(lines)


def _echo_runs_result(records: list[RunRecord], *, store: RunStore | None, output: OutputFormat, total: int | None = None) -> None:
    resolved_output = _resolve_output_format(output)
    if resolved_output == OutputFormat.SUMMARY:
        typer.echo(_render_runs_summary(records, store=store, total=total))
        return
    if resolved_output == OutputFormat.JSON_SUMMARY:
        typer.echo(json.dumps(_build_runs_summary(records, store=store), indent=2))
        return

    payload: list[dict[str, Any]] = [record.model_dump(mode="json") for record in records]
    typer.echo(json.dumps(payload, indent=2))


def _get_run_or_exit(store: RunStore, run_id: str, *, runs_dir: str) -> RunRecord:
    try:
        return store.get_run(run_id)
    except KeyError as exc:
        typer.echo(f"Run `{run_id}` not found in `{runs_dir}`.", err=True)
        raise typer.Exit(code=1) from exc


def _run_pipeline(pipeline: PipelineSpec, runs_dir: str, max_concurrent_runs: int, output: OutputFormat) -> None:
    store, orchestrator = _build_runtime(runs_dir, max_concurrent_runs)

    async def _run() -> None:
        run_record = await orchestrator.submit(pipeline)
        completed = await orchestrator.wait(run_record.id, timeout=None)
        run_dir = store.run_dir(run_record.id)
        _echo_run_result(completed, output=output, run_dir=run_dir)
        raise typer.Exit(code=0 if _status_value(completed.status) == "completed" else 1)

    asyncio.run(_run())


def _run_pipeline_path(path: str, runs_dir: str, max_concurrent_runs: int, output: OutputFormat) -> None:
    _run_pipeline(_load_pipeline(path), runs_dir, max_concurrent_runs, output)


def _is_click_testing_stream(stream: object) -> bool:
    stream_type = type(stream)
    return stream_type.__module__ == "click.testing" and stream_type.__name__ == "_NamedTextIOWrapper"


def _stream_supports_tty_summary(*, err: bool) -> bool:
    stream = sys.stderr if err else sys.stdout
    if _is_click_testing_stream(stream):
        return True
    isatty = getattr(stream, "isatty", None)
    return bool(callable(isatty) and isatty())


def _parse_template_settings(raw_settings: list[str] | None) -> dict[str, str]:
    settings: dict[str, str] = {}
    for raw_setting in raw_settings or []:
        key, separator, value = raw_setting.partition("=")
        if separator != "=" or not key or not value:
            raise ValueError(f"template settings must use KEY=VALUE form, got `{raw_setting}`")
        if key in settings:
            raise ValueError(f"template setting `{key}` was provided more than once")
        settings[key] = value
    return settings


@app.command()
def validate(path: str) -> None:
    pipeline = _load_pipeline(path)
    typer.echo(json.dumps(pipeline.model_dump(mode="json"), indent=2))


@app.command()
def templates() -> None:
    lines = ["Bundled templates:"]
    for template in bundled_templates():
        details = [
            f"source: `examples/{template.example_name}`",
            f"use: `agentflow init --template {template.name}`",
        ]
        if template.support_files:
            details.insert(0, "assets: " + ", ".join(f"`{path}`" for path in template.support_files))
        if template.parameters:
            details.insert(
                0,
                "params: " + ", ".join(f"`{parameter.name}={parameter.default}`" for parameter in template.parameters),
            )
        lines.append(
            f"- {template.name}: {template.description} "
            f"({'; '.join(details)})"
        )
    typer.echo("\n".join(lines))


@app.command()
def init(
    path: str = typer.Argument(
        "",
        help="Optional destination path. When omitted or `-`, print the selected template to stdout.",
    ),
    template: str = typer.Option(
        "pipeline",
        "--template",
        "-t",
        help=f"Bundled template name ({', '.join(bundled_template_names())}). Use `agentflow templates` to list details.",
    ),
    force: bool = typer.Option(
        False,
        "--force",
        help="Overwrite an existing destination file.",
    ),
    set_value: list[str] = typer.Option(
        None,
        "--set",
        help="Template setting in KEY=VALUE form. Repeat to customize parameterized templates.",
    ),
) -> None:
    try:
        template_settings = _parse_template_settings(set_value)
    except ValueError as exc:
        raise typer.BadParameter(str(exc), param_hint="--set") from exc

    try:
        rendered_template = render_bundled_template(template, values=template_settings)
    except ValueError as exc:
        param_hint = "--template" if template not in bundled_template_names() else "--set"
        raise typer.BadParameter(str(exc), param_hint=param_hint) from exc
    support_files = rendered_template.support_files

    if not path or path == "-":
        if support_files:
            typer.echo(
                f"Template `{template}` includes support files and requires a destination path.",
                err=True,
            )
            raise typer.Exit(code=1)
        typer.echo(rendered_template.content, nl=False)
        return

    destination = Path(path).expanduser()
    if destination.exists() and destination.is_dir():
        typer.echo(f"Destination `{destination}` is a directory.", err=True)
        raise typer.Exit(code=1)
    if destination.exists() and not force:
        typer.echo(f"Destination `{destination}` already exists. Use `--force` to overwrite it.", err=True)
        raise typer.Exit(code=1)

    support_copies: list[tuple[str, str, Path]] = []
    for support_file in support_files:
        target = destination.parent / support_file.relative_path
        support_copies.append((support_file.relative_path, support_file.content, target))
        if target.exists() and not force:
            typer.echo(f"Destination `{target}` already exists. Use `--force` to overwrite it.", err=True)
            raise typer.Exit(code=1)

    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(rendered_template.content, encoding="utf-8")
    for _relative_path, content, target in support_copies:
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")
    typer.echo(f"Wrote `{template}` template to `{destination}`.")


@app.command()
def runs(
    runs_dir: str = typer.Option(".agentflow/runs", envvar="AGENTFLOW_RUNS_DIR"),
    output: OutputFormat = typer.Option(
        OutputFormat.AUTO,
        "--output",
        help="Result output format. Defaults to `summary` on a terminal and `json` otherwise.",
    ),
    limit: int = typer.Option(20, min=0, help="Maximum runs to show. Use `0` to show all persisted runs."),
) -> None:
    store = _build_store(runs_dir)
    all_runs = store.list_runs()
    selected_runs = all_runs if limit == 0 else all_runs[:limit]
    _echo_runs_result(selected_runs, store=store, output=output, total=len(all_runs))


@app.command()
def show(
    run_id: str,
    runs_dir: str = typer.Option(".agentflow/runs", envvar="AGENTFLOW_RUNS_DIR"),
    output: OutputFormat = typer.Option(
        OutputFormat.AUTO,
        "--output",
        help="Result output format. Defaults to `summary` on a terminal and `json` otherwise.",
    ),
) -> None:
    store = _build_store(runs_dir)
    record = _get_run_or_exit(store, run_id, runs_dir=runs_dir)
    _echo_run_result(record, output=output, run_dir=_run_dir_for_record(store, run_id))


@app.command()
def cancel(
    run_id: str,
    runs_dir: str = typer.Option(".agentflow/runs", envvar="AGENTFLOW_RUNS_DIR"),
    max_concurrent_runs: int = typer.Option(2, envvar="AGENTFLOW_MAX_CONCURRENT_RUNS"),
    output: OutputFormat = typer.Option(
        OutputFormat.AUTO,
        "--output",
        help="Result output format. Defaults to `summary` on a terminal and `json` otherwise.",
    ),
) -> None:
    store, orchestrator = _build_runtime(runs_dir, max_concurrent_runs)

    async def _cancel() -> None:
        try:
            record = await orchestrator.cancel(run_id)
        except KeyError as exc:
            typer.echo(f"Run `{run_id}` not found in `{runs_dir}`.", err=True)
            raise typer.Exit(code=1) from exc
        _echo_run_result(record, output=output, run_dir=_run_dir_for_record(store, record.id))

    asyncio.run(_cancel())


@app.command()
def rerun(
    run_id: str,
    runs_dir: str = typer.Option(".agentflow/runs", envvar="AGENTFLOW_RUNS_DIR"),
    max_concurrent_runs: int = typer.Option(2, envvar="AGENTFLOW_MAX_CONCURRENT_RUNS"),
    output: OutputFormat = typer.Option(
        OutputFormat.AUTO,
        "--output",
        help="Result output format. Defaults to `summary` on a terminal and `json` otherwise.",
    ),
) -> None:
    store, orchestrator = _build_runtime(runs_dir, max_concurrent_runs)

    async def _rerun() -> None:
        try:
            record = await orchestrator.rerun(run_id)
        except KeyError as exc:
            typer.echo(f"Run `{run_id}` not found in `{runs_dir}`.", err=True)
            raise typer.Exit(code=1) from exc
        completed = await orchestrator.wait(record.id, timeout=None)
        _echo_run_result(completed, output=output, run_dir=_run_dir_for_record(store, record.id))
        raise typer.Exit(code=0 if _status_value(completed.status) == "completed" else 1)

    asyncio.run(_rerun())


@app.command()
def resume(
    run_id: str,
    runs_dir: str = typer.Option(".agentflow/runs", envvar="AGENTFLOW_RUNS_DIR"),
    max_concurrent_runs: int = typer.Option(2, envvar="AGENTFLOW_MAX_CONCURRENT_RUNS"),
    output: OutputFormat = typer.Option(
        OutputFormat.AUTO,
        "--output",
        help="Result output format. Defaults to `summary` on a terminal and `json` otherwise.",
    ),
) -> None:
    """Resume a failed or cancelled run from where it left off.

    Completed nodes are preserved and skipped; failed/cancelled/skipped nodes
    are reset to pending and re-executed. The scratchboard and artifacts from
    completed nodes are copied to the new run.
    """
    store, orchestrator = _build_runtime(runs_dir, max_concurrent_runs)

    async def _resume() -> None:
        try:
            record = await orchestrator.resume(run_id)
        except KeyError as exc:
            typer.echo(f"Run `{run_id}` not found in `{runs_dir}`.", err=True)
            raise typer.Exit(code=1) from exc
        except ValueError as exc:
            typer.echo(str(exc), err=True)
            raise typer.Exit(code=1) from exc
        typer.echo(f"Resumed as new run `{record.id}` (preserving completed nodes from `{run_id}`).")
        completed = await orchestrator.wait(record.id, timeout=None)
        _echo_run_result(completed, output=output, run_dir=_run_dir_for_record(store, record.id))
        raise typer.Exit(code=0 if _status_value(completed.status) == "completed" else 1)

    asyncio.run(_resume())


@app.command()
def evolve(
    run_id: str,
    node: list[str] = typer.Option(..., "--node", "-n", help="Source node ids to harvest traces from."),
    target: str = typer.Option("codex", help="Base agent kind to evolve."),
    optimizer: str = typer.Option("codex", help="Optimizer agent kind to patch the cloned repo."),
    profile: str = typer.Option("", "--profile", help="Tuner profile name under `agent_tuner/`. Defaults to `target`."),
    runs_dir: str = typer.Option(".agentflow/runs", envvar="AGENTFLOW_RUNS_DIR"),
    output: OutputFormat = typer.Option(
        OutputFormat.SUMMARY,
        "--output",
        help="Structured output format for evolution results.",
    ),
) -> None:
    store = _build_store(runs_dir)
    record = _get_run_or_exit(store, run_id, runs_dir=runs_dir)
    pipeline_nodes = record.pipeline.node_map
    missing_nodes = [node_id for node_id in node if node_id not in pipeline_nodes]
    if missing_nodes:
        typer.echo(f"Unknown node ids for run `{run_id}`: {missing_nodes}", err=True)
        raise typer.Exit(code=1)

    normalized_target = target.strip()
    selected_nodes = [
        node_id
        for node_id in node
        if normalize_agent_name(pipeline_nodes[node_id].agent) == normalized_target
    ]
    if not selected_nodes:
        typer.echo(
            f"No selected nodes in run `{run_id}` use target agent `{normalized_target}`.",
            err=True,
        )
        raise typer.Exit(code=1)

    payload = {
        "profile": (profile.strip() or normalized_target),
        "target": normalized_target,
        "optimizer": optimizer.strip(),
        "source_nodes": selected_nodes,
        "trace_paths": {
            node_id: str(store.artifact_path(run_id, node_id, "trace.jsonl"))
            for node_id in selected_nodes
        },
        "workspace_dir": record.pipeline.working_dir,
        "run_id": run_id,
    }
    try:
        result = run_evolution_from_payload(payload)
    except (FileNotFoundError, RuntimeError, ValueError) as exc:
        typer.echo(str(exc), err=True)
        raise typer.Exit(code=1) from exc

    if output == OutputFormat.JSON:
        typer.echo(json.dumps(result, ensure_ascii=False, indent=2))
        return
    typer.echo(_render_evolution_summary(result))


@app.command("tuned-agents")
def tuned_agents(
    workspace: str = typer.Option(".", help="Workspace root that holds `.agentflow/tuned_agents`."),
    output: OutputFormat = typer.Option(
        OutputFormat.SUMMARY,
        "--output",
        help="Structured output format for tuned agent listings.",
    ),
) -> None:
    records = list_tuned_agent_records(Path(workspace).expanduser().resolve())
    if output == OutputFormat.JSON:
        typer.echo(
            json.dumps(
                [record.model_dump(mode="json") for record in records],
                ensure_ascii=False,
                indent=2,
            )
        )
        return
    typer.echo(_render_tuned_agents_summary(records))


@app.command("tuned-agent")
def tuned_agent(
    name: str,
    workspace: str = typer.Option(".", help="Workspace root that holds `.agentflow/tuned_agents`."),
    output: OutputFormat = typer.Option(
        OutputFormat.SUMMARY,
        "--output",
        help="Structured output format for tuned agent details.",
    ),
) -> None:
    records = {record.name: record for record in list_tuned_agent_records(Path(workspace).expanduser().resolve())}
    record = records.get(name)
    if record is None:
        typer.echo(f"Tuned agent `{name}` not found.", err=True)
        raise typer.Exit(code=1)
    latest = resolve_tuned_agent_version(Path(workspace).expanduser().resolve(), name)
    payload = record.model_dump(mode="json")
    payload["latest"] = latest.model_dump(mode="json") if latest is not None else None
    if output == OutputFormat.JSON:
        typer.echo(json.dumps(payload, ensure_ascii=False, indent=2))
        return
    typer.echo(_render_tuned_agent_detail(record))


@app.command()
def run(
    path: str,
    runs_dir: str = typer.Option(".agentflow/runs", envvar="AGENTFLOW_RUNS_DIR"),
    max_concurrent_runs: int = typer.Option(2, envvar="AGENTFLOW_MAX_CONCURRENT_RUNS"),
    output: OutputFormat = typer.Option(
        OutputFormat.AUTO,
        "--output",
        help="Result output format. Defaults to `summary` on a terminal and `json` otherwise.",
    ),
) -> None:
    _run_pipeline(_load_pipeline(path), runs_dir, max_concurrent_runs, output)


@app.command()
def smoke(
    path: str = typer.Argument("", help="Optional pipeline path. Defaults to the bundled real-agent smoke example."),
    runs_dir: str = typer.Option(".agentflow/runs", envvar="AGENTFLOW_RUNS_DIR"),
    max_concurrent_runs: int = typer.Option(2, envvar="AGENTFLOW_MAX_CONCURRENT_RUNS"),
    output: OutputFormat = typer.Option(OutputFormat.SUMMARY, "--output", help="Result output format."),
) -> None:
    selected_path = path or default_smoke_pipeline_path()
    _run_pipeline(_load_pipeline(selected_path), runs_dir, max_concurrent_runs, output)


def main() -> None:
    app()


if __name__ == "__main__":
    main()
