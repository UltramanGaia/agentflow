from __future__ import annotations

import os
import shlex
from pathlib import Path
from typing import Any

from jinja2 import TemplateError
from agentflow.local_shell import (
    target_bash_login_startup_file_statuses,
    render_shell_init,
    shell_command_prefix_env_value,
    shell_init_exported_env_var_value,
    summarize_target_bash_login_startup,
    target_uses_bash,
    shell_template_exported_env_var_value_before_command,
    target_bash_home,
    target_bash_login_startup_warning,
    target_bash_startup_exports_env_var,
    target_uses_interactive_bash,
    target_uses_login_bash,
)
from agentflow.agents.registry import AdapterRegistry, default_adapter_registry
from agentflow.context import render_node_prompt
from agentflow.prepared import build_execution_paths
from agentflow.runner import RunnerRegistry, default_runner_registry
from agentflow.specs import AgentKind, NodeResult, NodeSpec, NodeStatus, PipelineSpec, normalize_agent_name, resolve_provider
from agentflow.tuned_agents import resolve_node_for_execution
from agentflow.utils import looks_sensitive_key, redact_sensitive_shell_text, redact_sensitive_shell_value

_REDACTED = "<redacted>"
_GENERATED = "<generated>"
_INSPECT_PLACEHOLDER_PREFIX = "<inspect placeholder for nodes."
_OK_LAUNCH_ENV_OVERRIDE_SOURCES = {
    "node.env",
}


def _auto_preflight_summary(value: Any) -> str | None:
    if not isinstance(value, dict):
        return None
    enabled = value.get("enabled")
    reason = value.get("reason")
    if not isinstance(reason, str) or not reason:
        return None
    status = "enabled" if enabled else "disabled"
    return f"{status} - {reason}"


def _auto_preflight_match_summary(value: Any) -> list[str]:
    if not isinstance(value, dict):
        return []
    matches = value.get("match_summary")
    if not isinstance(matches, list):
        return []
    return [match for match in matches if isinstance(match, str) and match]

def _preview_text(text: str | None, *, limit: int = 100) -> str | None:
    if text is None:
        return None
    collapsed = " ".join(text.split())
    if not collapsed:
        return None
    if len(collapsed) <= limit:
        return collapsed
    return collapsed[: limit - 1].rstrip() + "…"


def _command_text(command: list[str] | None) -> str | None:
    if not command:
        return None
    return shlex.join(command)


def _placeholder_text(node_id: str, field: str) -> str:
    return f"<inspect placeholder for nodes.{node_id}.{field}>"


def _prompt_uses_placeholder_results(prompt: str) -> bool:
    return _INSPECT_PLACEHOLDER_PREFIX in prompt


def _build_placeholder_results(pipeline: PipelineSpec) -> dict[str, NodeResult]:
    results: dict[str, NodeResult] = {}
    for node in pipeline.nodes:
        output = _placeholder_text(node.id, "output")
        result = NodeResult(
            node_id=node.id,
            status=NodeStatus.PENDING,
            output=output,
            final_response=_placeholder_text(node.id, "final_response"),
            stdout_lines=[_placeholder_text(node.id, "stdout")],
            stderr_lines=[_placeholder_text(node.id, "stderr")],
        )
        results[node.id] = result
    return results


# Keep non-secret debugging values readable while redacting likely credentials.
def _sanitize_env(env: dict[str, str]) -> dict[str, str]:
    return {
        key: (_REDACTED if looks_sensitive_key(key) else value)
        for key, value in sorted(env.items())
    }


def _sanitize_payload(value: Any, *, key: str | None = None) -> Any:
    if isinstance(value, dict):
        if key == "env":
            string_env = {env_key: str(env_value) for env_key, env_value in value.items()}
            return _sanitize_env(string_env)
        if key == "runtime_files":
            return {runtime_key: _GENERATED for runtime_key in sorted(value)}
        return {inner_key: _sanitize_payload(inner_value, key=inner_key) for inner_key, inner_value in value.items()}
    if isinstance(value, list):
        return [_sanitize_payload(item) for item in value]
    if key and looks_sensitive_key(key):
        return _REDACTED
    return value


def _sanitize_target(target: dict[str, Any]) -> dict[str, Any]:
    sanitized = dict(target)
    for key in ("shell", "shell_init"):
        if key in sanitized:
            sanitized[key] = redact_sensitive_shell_value(sanitized[key])
    return sanitized


def _render_prompt_for_inspection(
    pipeline: PipelineSpec,
    node: NodeSpec,
    placeholder_results: dict[str, NodeResult],
) -> tuple[str, str | None]:
    try:
        return render_node_prompt(pipeline, node, placeholder_results), None
    except (KeyError, OSError, TemplateError, TypeError, ValueError) as exc:
        return node.prompt, str(exc)


def _payload_summary(node_plan: dict[str, Any]) -> str | None:
    launch = node_plan["launch"]
    payload = launch.get("payload")
    if not isinstance(payload, dict):
        return None
    return None


def _provider_summary(node_plan: dict[str, Any]) -> str | None:
    provider = node_plan.get("resolved_provider")
    if not isinstance(provider, dict):
        return None

    parts: list[str] = []
    name = provider.get("name")
    if name:
        parts.append(str(name))

    if not parts:
        return None
    return ", ".join(parts)


def _has_nonempty_env_value(env: object, key: str) -> bool:
    return isinstance(env, dict) and bool(str(env.get(key, "")).strip())


def _has_nonempty_shell_value(value: str | None) -> bool:
    return bool(isinstance(value, str) and value.strip())


def _env_declares_key(env: object, key: str) -> bool:
    return isinstance(env, dict) and key in env


def _bootstrap_override_origin(
    launch_env: dict[str, str],
    key: str,
) -> tuple[str | None, str]:
    current_value = str(os.getenv(key, "") or "")
    launch_value = str(launch_env.get(key, "") or "")
    if key in launch_env and launch_value.strip() and (not current_value.strip() or launch_value != current_value):
        return "launch_env", launch_value
    if current_value.strip():
        return "current_environment", current_value
    return None, ""


def _local_launch_env(node: NodeSpec, resolved_provider: object) -> dict[str, str]:
    env: dict[str, str] = {}
    if isinstance(node.env, dict):
        env.update({str(key): str(value) for key, value in node.env.items() if value is not None})
    return env


def _resolved_auth_requirement(node: NodeSpec) -> tuple[str | None, str | None]:
    return None, None


def _format_auth_source_summary(
    api_key_env: str,
    primary: tuple[str, str],
    bootstrap_hint: tuple[str, str] | None = None,
) -> str:
    summary = f"`{api_key_env}` via {primary[0]}"
    if bootstrap_hint is not None and bootstrap_hint[1] != primary[1]:
        summary += f"; {bootstrap_hint[0]} also runs before launch"
    return summary


def _bash_startup_auth_source_label(target: object) -> tuple[str, str] | None:
    if getattr(target, "kind", None) != "local":
        return None

    uses_login_bash = target_uses_login_bash(target)
    uses_interactive_bash = target_uses_interactive_bash(target)
    if uses_login_bash and uses_interactive_bash:
        return ("local bash login and interactive startup files", "target.bash_startup")
    if uses_login_bash:
        return ("local bash login startup files", "target.bash_startup")
    if uses_interactive_bash:
        return ("local bash interactive startup files", "target.bash_startup")
    return None


def _auth_summary(
    node: NodeSpec,
    resolved_provider: object,
    launch_env: dict[str, str] | None = None,
    *,
    cwd: str | None = None,
) -> str | None:
    api_key_env, provider_name = _resolved_auth_requirement(node)
    if not api_key_env:
        if node.agent in {AgentKind.CODEX, AgentKind.CLAUDE, AgentKind.PI, AgentKind.GAIA}:
            return "uses the agent's configured auth/runtime profile"
        return None

    if _has_nonempty_env_value(node.env, api_key_env):
        return _format_auth_source_summary(
            api_key_env,
            ("`node.env`", "node.env"),
        )

    return _format_auth_source_summary(api_key_env, ("the agent config", "agent config"))


def _local_bootstrap_auth_override_source(
    node: NodeSpec,
    resolved_provider: object,
    api_key_env: str,
    launch_env: dict[str, str] | None = None,
    *,
    cwd: str | None = None,
) -> dict[str, str] | None:
    target = node.target
    if getattr(target, "kind", None) != "local":
        return None

    effective_home = target_bash_home(target, env=launch_env, cwd=cwd)
    shell_init = getattr(target, "shell_init", None)
    if _has_nonempty_shell_value(
        shell_init_exported_env_var_value(
            shell_init,
            api_key_env,
            home=effective_home,
            cwd=cwd,
            env=launch_env,
        )
    ):
        return {"source": "target.shell_init"}

    shell = getattr(target, "shell", None)
    if _has_nonempty_shell_value(
        shell_template_exported_env_var_value_before_command(
            shell if isinstance(shell, str) else None,
            api_key_env,
            home=effective_home,
            cwd=cwd,
            env=launch_env,
            interactive_bash=target_uses_interactive_bash(target),
        )
    ) or _has_nonempty_shell_value(shell_command_prefix_env_value(shell if isinstance(shell, str) else None, api_key_env)):
        return {"source": "target.shell"}

    return None


def _bootstrap_summary(
    target: dict[str, Any],
    launch_env: dict[str, str] | None = None,
    *,
    cwd: str | None = None,
) -> str | None:
    if target.get("kind") != "local":
        return None

    parts: list[str] = []
    shell = target.get("shell")
    if shell:
        parts.append(f"shell={redact_sensitive_shell_text(shell)}")

    uses_login_bash = target_uses_login_bash(target)
    if uses_login_bash:
        parts.append("login=true")

    login_startup = summarize_target_bash_login_startup(target, env=launch_env, cwd=cwd)
    if login_startup is not None:
        parts.append(f"startup={login_startup}")

    if target_uses_interactive_bash(target):
        parts.append("interactive=true")

    shell_init = render_shell_init(target.get("shell_init"))
    if shell_init:
        parts.append(f"init={redact_sensitive_shell_text(shell_init)}")

    if not parts:
        return None
    return ", ".join(parts)


def _bootstrap_home(
    target: dict[str, Any],
    launch_env: dict[str, str] | None = None,
    *,
    cwd: str | None = None,
) -> str | None:
    if target.get("kind") != "local" or not target_uses_bash(target):
        return None

    effective_home = target_bash_home(target, env=launch_env, cwd=cwd).resolve()
    try:
        process_home = Path.home().resolve()
    except RuntimeError:
        process_home = None

    if process_home is not None and effective_home == process_home:
        return None
    return str(effective_home)


def auth_summary_depends_on_local_shell_bootstrap(auth_summary: str | None) -> bool:
    if not isinstance(auth_summary, str):
        return False
    return auth_summary.startswith("expects `") and "local shell bootstrap" in auth_summary


def _inspection_target_uses_local_shell_bootstrap(node: dict[str, Any]) -> bool:
    target = node.get("target")
    if not isinstance(target, dict) or target.get("kind") != "local":
        return False
    if str(target.get("bootstrap") or "").strip():
        return True
    if bool(target.get("shell_login")) or bool(target.get("shell_interactive")):
        return True
    shell = target.get("shell")
    if isinstance(shell, str) and shell.strip():
        return True
    shell_init = target.get("shell_init")
    if isinstance(shell_init, str):
        return bool(shell_init.strip())
    if isinstance(shell_init, list):
        return any(isinstance(command, str) and command.strip() for command in shell_init)
    return False


def _target_warnings(
    target: dict[str, Any],
    launch_env: dict[str, str] | None = None,
    *,
    cwd: str | None = None,
) -> list[str]:
    warnings: list[str] = []

    login_startup_warning = target_bash_login_startup_warning(target, env=launch_env, cwd=cwd)
    if login_startup_warning is not None:
        warnings.append(login_startup_warning)

    return warnings


def _launch_env_override_warning(key: str, current_value: str, launch_value: str) -> str | None:
    if not current_value.strip() or current_value == launch_value:
        return None

    if key.endswith("_CUSTOM_HEADERS") or looks_sensitive_key(key):
        if not launch_value.strip():
            return f"Launch env clears current `{key}` for this node."
        return f"Launch env overrides current `{key}` for this node."

    return None


def _launch_env_override_source_label(detail: dict[str, Any]) -> str | None:
    source = detail.get("source")
    if not isinstance(source, str) or not source:
        return None

    return f"`{source}`"


def _bootstrap_env_override_source_label(detail: dict[str, Any]) -> str | None:
    source = detail.get("source")
    if not isinstance(source, str) or not source:
        return None

    if source == "target.bash_startup":
        return "local bash startup files"

    return f"`{source}`"


def _format_launch_env_override_detail(detail: dict[str, Any]) -> str:
    key = str(detail["key"])
    source_label = _launch_env_override_source_label(detail)
    source_suffix = f" via {source_label}" if source_label else ""

    if detail.get("redacted"):
        if detail.get("cleared"):
            return f"Launch env clears current `{key}` for this node{source_suffix}."
        return f"Launch env overrides current `{key}` for this node{source_suffix}."

    current_value = str(detail.get("current_value", ""))
    launch_value = str(detail.get("launch_value", ""))
    if not launch_value.strip():
        return f"Launch env clears current `{key}` value `{current_value}`{source_suffix}."

    return (
        f"Launch env overrides current `{key}` from `{current_value}` to `{launch_value}`"
        f"{source_suffix}."
    )


def _launch_env_override_status(detail: dict[str, Any]) -> str:
    source = detail.get("source")
    if isinstance(source, str) and source in _OK_LAUNCH_ENV_OVERRIDE_SOURCES:
        return "ok"
    return "warning"


def _format_bootstrap_env_override_detail(detail: dict[str, Any]) -> str:
    key = str(detail["key"])
    source_label = _bootstrap_env_override_source_label(detail)
    source_suffix = f" via {source_label}" if source_label else ""
    subject = "launch" if detail.get("origin") == "launch_env" else "current"
    if not detail.get("redacted"):
        current_value = str(detail.get("current_value", ""))
        bootstrap_value = str(detail.get("bootstrap_value", ""))
        origin = str(detail.get("origin", "current_environment") or "current_environment")
        subject = "launch" if origin == "launch_env" else "current"
        if not current_value.strip():
            return f"Local shell bootstrap sets {subject} `{key}` to `{bootstrap_value}`{source_suffix}."
        return (
            f"Local shell bootstrap overrides {subject} `{key}` from `{current_value}` "
            f"to `{bootstrap_value}`{source_suffix}."
        )
    return f"Local shell bootstrap overrides {subject} `{key}` for this node{source_suffix}."


def _launch_env_override_source(node: NodeSpec, resolved_provider: Any, key: str) -> dict[str, str] | None:
    if _env_declares_key(node.env, key):
        return {"source": "node.env"}

    return None


def _launch_env_override_details(
    node: NodeSpec,
    resolved_provider: Any,
    launch_env: dict[str, str],
) -> list[dict[str, Any]]:
    details: list[dict[str, Any]] = []
    for key, launch_value in sorted(launch_env.items()):
        current_value = os.getenv(key)
        if current_value is None:
            continue

        warning = _launch_env_override_warning(key, str(current_value), str(launch_value))
        if warning is None:
            continue

        detail: dict[str, Any] = {"key": key}
        detail["redacted"] = True
        if not str(launch_value).strip():
            detail["cleared"] = True
        source = _launch_env_override_source(node, resolved_provider, key)
        if source:
            detail.update(source)
        details.append(detail)
    return details


def _launch_env_override_warnings(
    node: NodeSpec,
    resolved_provider: Any,
    launch_env: dict[str, str],
) -> list[str]:
    return [
        _format_launch_env_override_detail(detail)
        for detail in _launch_env_override_details(node, resolved_provider, launch_env)
        if _launch_env_override_status(detail) == "warning"
    ]


def _launch_env_override_notes(
    node: NodeSpec,
    resolved_provider: Any,
    launch_env: dict[str, str],
) -> list[str]:
    return [
        _format_launch_env_override_detail(detail)
        for detail in _launch_env_override_details(node, resolved_provider, launch_env)
        if _launch_env_override_status(detail) == "ok"
    ]


def _bootstrap_env_override_details(
    node: NodeSpec,
    resolved_provider: Any,
    launch_env: dict[str, str],
    *,
    cwd: str | None = None,
) -> list[dict[str, Any]]:
    details: list[dict[str, Any]] = []
    api_key_env, _provider_name = _resolved_auth_requirement(node)
    if api_key_env:
        origin, pre_bootstrap_value = _bootstrap_override_origin(launch_env, api_key_env)
        if origin is not None and pre_bootstrap_value.strip():
            source = _local_bootstrap_auth_override_source(
                node,
                resolved_provider,
                api_key_env,
                launch_env,
                cwd=cwd,
            )
            if source is not None:
                if source is not None:
                    detail: dict[str, Any] = {"key": api_key_env}
                    if looks_sensitive_key(api_key_env):
                        detail["redacted"] = True
                    if origin == "launch_env":
                        detail["origin"] = origin
                    detail.update(source)
                    details.append(detail)

    return details


def _bootstrap_env_override_warnings(
    node: NodeSpec,
    resolved_provider: Any,
    launch_env: dict[str, str],
    *,
    cwd: str | None = None,
) -> list[str]:
    return [
        _format_bootstrap_env_override_detail(detail)
        for detail in _bootstrap_env_override_details(node, resolved_provider, launch_env, cwd=cwd)
    ]


def _bootstrap_env_override_notes(
    node: NodeSpec,
    resolved_provider: Any,
    launch_env: dict[str, str],
    *,
    cwd: str | None = None,
) -> list[str]:
    return [
        _format_bootstrap_env_override_detail(detail)
        for detail in _bootstrap_env_override_details(node, resolved_provider, launch_env, cwd=cwd)
    ]


def _local_bootstrap_sets_env_var(
    target: Any,
    env_var: str,
    *,
    env: dict[str, str] | None = None,
    cwd: str | None = None,
) -> bool:
    if getattr(target, "kind", None) != "local":
        return False

    effective_home = target_bash_home(target, env=env, cwd=cwd)
    shell_init = getattr(target, "shell_init", None)
    if shell_init_exports_env_var(shell_init, env_var, home=effective_home, cwd=cwd, env=env):
        return True

    shell = getattr(target, "shell", None)
    if shell_template_exports_env_var_before_command(
        shell if isinstance(shell, str) else None,
        env_var,
        home=effective_home,
        cwd=cwd,
        env=env,
        interactive_bash=target_uses_interactive_bash(target),
    ):
        return True
    if shell_command_prefixes_env_var(shell if isinstance(shell, str) else None, env_var):
        return True

    if target_bash_startup_exports_env_var(target, env_var, home=effective_home, env=env, cwd=cwd):
        return True

    return False


def _format_launch_env_inheritance_detail(node: NodeSpec, detail: dict[str, Any]) -> str:
    key = str(detail["key"])
    current_value = str(detail["current_value"])
    agent_name = normalize_agent_name(node.agent).capitalize()
    return (
        f"Launch inherits current `{key}` value `{current_value}`; configure `node.env` "
        f"explicitly if you want {agent_name} routing pinned for this node."
    )


def _launch_env_inheritance_details(
    node: NodeSpec,
    resolved_provider: Any,
    launch_env: dict[str, str],
    *,
    cwd: str | None = None,
) -> list[dict[str, Any]]:
    return []


def _launch_env_inheritance_warnings(
    node: NodeSpec,
    resolved_provider: Any,
    launch_env: dict[str, str],
    *,
    cwd: str | None = None,
) -> list[str]:
    return [
        _format_launch_env_inheritance_detail(node, detail)
        for detail in _launch_env_inheritance_details(node, resolved_provider, launch_env, cwd=cwd)
    ]


def _execution_mode_summary(node_plan: dict[str, Any]) -> str | None:
    parts: list[str] = []

    tools = node_plan.get("tools")
    if tools:
        parts.append(f"tools={tools}")

    capture = node_plan.get("capture")
    if capture:
        parts.append(f"capture={capture}")

    if not parts:
        return None
    return ", ".join(parts)


def build_launch_inspection(
    pipeline: PipelineSpec,
    *,
    runs_dir: str,
    node_ids: list[str] | None = None,
    adapters: AdapterRegistry = default_adapter_registry,
    runners: RunnerRegistry = default_runner_registry,
) -> dict[str, Any]:
    requested_nodes = set(node_ids or [])
    available_nodes = {node.id for node in pipeline.nodes}
    missing_nodes = sorted(requested_nodes - available_nodes)
    if missing_nodes:
        raise ValueError(f"unknown node ids: {missing_nodes}")

    placeholder_results = _build_placeholder_results(pipeline)
    base_dir = Path(runs_dir).expanduser().resolve()
    inspected_nodes: list[dict[str, Any]] = []
    uses_placeholder_results = False

    for node in pipeline.nodes:
        if requested_nodes and node.id not in requested_nodes:
            continue

        prompt, render_error = _render_prompt_for_inspection(pipeline, node, placeholder_results)
        uses_placeholder_results = uses_placeholder_results or _prompt_uses_placeholder_results(prompt)
        execution_resolution = resolve_node_for_execution(node, pipeline.working_path)
        execution_node = execution_resolution.node
        resolved_provider = resolve_provider(execution_node.provider, execution_node.agent)
        paths = build_execution_paths(
            base_dir=base_dir,
            pipeline_workdir=pipeline.working_path,
            run_id="inspect",
            node_id=node.id,
            node_target=execution_node.target,
            create_runtime_dir=False,
        )
        prepared = adapters.get(execution_resolution.runtime_agent).prepare(execution_node, prompt, paths)
        launch = runners.get(execution_node.target.kind).plan_execution(execution_node, prepared, paths)

        node_plan = {
            "id": node.id,
            "agent": normalize_agent_name(node.agent),
            "runtime_agent": execution_resolution.runtime_agent.value,
            "model": node.model,
            "schedule": node.schedule.model_dump(mode="json") if node.schedule is not None else None,
            "tools": node.tools.value,
            "capture": node.capture.value,
            "skills": list(node.skills),
            "depends_on": list(node.depends_on),
            "provider": node.provider.model_dump(mode="json") if hasattr(node.provider, "model_dump") else node.provider,
            "resolved_provider": resolved_provider.model_dump(mode="json") if resolved_provider is not None else None,
            "target": _sanitize_target(execution_node.target.model_dump(mode="json")),
            "rendered_prompt": prompt,
            "rendered_prompt_preview": _preview_text(prompt, limit=120),
            "render_error": render_error,
            "prepared": {
                "command": list(prepared.command),
                "command_text": _command_text(prepared.command),
                "cwd": prepared.cwd,
                "trace_kind": prepared.trace_kind,
                "env": _sanitize_env(prepared.env),
                "env_keys": sorted(prepared.env),
                "stdin": _preview_text(prepared.stdin, limit=120),
                "runtime_files": sorted(prepared.runtime_files),
            },
            "launch": {
                "kind": launch.kind,
                "command": redact_sensitive_shell_value(list(launch.command or [])),
                "command_text": redact_sensitive_shell_text(_command_text(launch.command) or "") or None,
                "cwd": launch.cwd,
                "env": _sanitize_env(launch.env),
                "env_keys": sorted(launch.env),
                "stdin": _preview_text(launch.stdin, limit=120),
                "runtime_files": list(launch.runtime_files),
                "payload": _sanitize_payload(launch.payload),
            },
        }
        launch_env = _local_launch_env(node, resolved_provider)
        auth_summary = _auth_summary(node, resolved_provider, launch_env, cwd=prepared.cwd)
        if auth_summary:
            node_plan["auth"] = auth_summary
        bootstrap_summary = _bootstrap_summary(node_plan["target"], prepared.env, cwd=prepared.cwd)
        if bootstrap_summary:
            node_plan["bootstrap"] = bootstrap_summary
        bootstrap_home = _bootstrap_home(node_plan["target"], prepared.env, cwd=prepared.cwd)
        if bootstrap_home:
            node_plan["bootstrap_home"] = bootstrap_home
        bash_startup_files = target_bash_login_startup_file_statuses(node.target, env=prepared.env, cwd=prepared.cwd)
        if bash_startup_files:
            node_plan["bash_startup_files"] = bash_startup_files
        launch_env_overrides = _launch_env_override_details(node, resolved_provider, prepared.env)
        if launch_env_overrides:
            node_plan["launch_env_overrides"] = launch_env_overrides
        bootstrap_env_overrides = _bootstrap_env_override_details(
            node,
            resolved_provider,
            prepared.env,
            cwd=prepared.cwd,
        )
        if bootstrap_env_overrides:
            node_plan["bootstrap_env_overrides"] = bootstrap_env_overrides
        launch_env_inheritances = _launch_env_inheritance_details(
            node,
            resolved_provider,
            prepared.env,
            cwd=prepared.cwd,
        )
        if launch_env_inheritances:
            node_plan["launch_env_inheritances"] = launch_env_inheritances
        node_plan["warnings"] = (
            _target_warnings(
                node_plan["target"],
                prepared.env,
                cwd=prepared.cwd,
            )
            + _launch_env_override_warnings(node, resolved_provider, prepared.env)
            + _launch_env_inheritance_warnings(node, resolved_provider, prepared.env, cwd=prepared.cwd)
        )
        node_plan["notes"] = (
            _launch_env_override_notes(node, resolved_provider, prepared.env)
            + _bootstrap_env_override_notes(node, resolved_provider, prepared.env, cwd=prepared.cwd)
        )
        node_plan["launch"]["payload_summary"] = _payload_summary(node_plan)
        inspected_nodes.append(node_plan)

    notes: list[str] = []
    if uses_placeholder_results:
        notes.append("Dependency references use placeholder node outputs because `inspect` does not execute the DAG.")

    return {
        "pipeline": {
            "name": pipeline.name,
            "description": pipeline.description,
            "working_dir": str(pipeline.working_path),
            "node_count": len(inspected_nodes),
        },
        "notes": notes,
        "nodes": inspected_nodes,
    }


def build_launch_inspection_summary(report: dict[str, Any]) -> dict[str, Any]:
    pipeline = {
        key: value
        for key, value in (report.get("pipeline") or {}).items()
        if value is not None
    }
    summary: dict[str, Any] = {
        "pipeline": pipeline,
        "nodes": [],
    }

    raw_auto_preflight = pipeline.get("auto_preflight")
    auto_preflight = _auto_preflight_summary(raw_auto_preflight)
    if auto_preflight:
        summary["pipeline"]["auto_preflight"] = auto_preflight
    auto_preflight_matches = _auto_preflight_match_summary(raw_auto_preflight)
    if auto_preflight_matches:
        summary["pipeline"]["auto_preflight_matches"] = auto_preflight_matches

    notes = report.get("notes")
    if notes:
        summary["notes"] = list(notes)

    for node in report.get("nodes", []):
        node_summary: dict[str, Any] = {
            "id": node["id"],
            "agent": node["agent"],
            "target": node["target"]["kind"],
        }
        depends_on = node.get("depends_on")
        if depends_on:
            node_summary["depends_on"] = list(depends_on)
        render_error = node.get("render_error")
        if render_error:
            node_summary["render_error"] = render_error
        model = node.get("model")
        if model:
            node_summary["model"] = model
        tools = node.get("tools")
        if tools:
            node_summary["tools"] = tools
        capture = node.get("capture")
        if capture:
            node_summary["capture"] = capture
        skills = node.get("skills")
        if skills:
            node_summary["skills"] = list(skills)
        provider_summary = _provider_summary(node)
        if provider_summary:
            node_summary["provider"] = provider_summary
        auth_summary = node.get("auth")
        if auth_summary:
            node_summary["auth"] = auth_summary
        bootstrap_summary = node.get("bootstrap")
        if bootstrap_summary:
            node_summary["bootstrap"] = bootstrap_summary
        bootstrap_home = node.get("bootstrap_home")
        if bootstrap_home:
            node_summary["bootstrap_home"] = bootstrap_home
        bash_startup_files = node.get("bash_startup_files")
        if bash_startup_files:
            node_summary["bash_startup_files"] = dict(bash_startup_files)
        shell_bridge = node.get("shell_bridge")
        if shell_bridge:
            node_summary["shell_bridge"] = dict(shell_bridge)
        prompt_preview = node.get("rendered_prompt_preview")
        if prompt_preview:
            node_summary["prompt_preview"] = prompt_preview
        prepared_command = node.get("prepared", {}).get("command_text")
        if prepared_command:
            node_summary["prepared_command"] = prepared_command
        launch_command = node.get("launch", {}).get("command_text")
        node_summary["launch"] = launch_command or node["launch"]["kind"]
        cwd = node.get("launch", {}).get("cwd") or node.get("prepared", {}).get("cwd")
        if cwd:
            node_summary["cwd"] = cwd
        env_keys = node.get("launch", {}).get("env_keys") or node.get("prepared", {}).get("env_keys")
        if env_keys:
            node_summary["env_keys"] = list(env_keys)
        runtime_files = node.get("launch", {}).get("runtime_files") or node.get("prepared", {}).get("runtime_files")
        if runtime_files:
            node_summary["runtime_files"] = list(runtime_files)
        payload_summary = node.get("launch", {}).get("payload_summary")
        if payload_summary:
            node_summary["payload"] = payload_summary
        warnings = node.get("warnings")
        if warnings:
            node_summary["warnings"] = list(warnings)
        notes = node.get("notes")
        if notes:
            node_summary["notes"] = list(notes)
        launch_env_overrides = node.get("launch_env_overrides")
        if launch_env_overrides:
            node_summary["launch_env_overrides"] = list(launch_env_overrides)
        bootstrap_env_overrides = node.get("bootstrap_env_overrides")
        if bootstrap_env_overrides:
            node_summary["bootstrap_env_overrides"] = list(bootstrap_env_overrides)
        launch_env_inheritances = node.get("launch_env_inheritances")
        if launch_env_inheritances:
            node_summary["launch_env_inheritances"] = list(launch_env_inheritances)
        summary["nodes"].append(node_summary)

    return summary


def render_launch_inspection_summary(report: dict[str, Any]) -> str:
    pipeline = report["pipeline"]
    lines = [f"Pipeline: {pipeline['name']}", f"Working dir: {pipeline['working_dir']}"]
    for note in report.get("notes", []):
        lines.append(f"Note: {note}")
    lines.append("Nodes:")

    for node in report.get("nodes", []):
        lines.append(f"- {node['id']} [{node['agent']}/{node['target']['kind']}]")
        if node["depends_on"]:
            lines.append(f"  Depends on: {', '.join(node['depends_on'])}")
        if node["render_error"]:
            lines.append(f"  Render error: {node['render_error']}")
        if node.get("model"):
            lines.append(f"  Model: {node['model']}")
        execution_mode_summary = _execution_mode_summary(node)
        if execution_mode_summary:
            lines.append(f"  Mode: {execution_mode_summary}")
        skills = node.get("skills") or []
        if skills:
            lines.append(f"  Skills: {', '.join(skills)}")
        provider_summary = _provider_summary(node)
        if provider_summary:
            lines.append(f"  Provider: {provider_summary}")
        auth_summary = node.get("auth")
        if auth_summary:
            lines.append(f"  Auth: {auth_summary}")
        bootstrap_summary = node.get("bootstrap")
        if bootstrap_summary:
            lines.append(f"  Bootstrap: {bootstrap_summary}")
        bootstrap_home = node.get("bootstrap_home")
        if bootstrap_home:
            lines.append(f"  Bootstrap home: {bootstrap_home}")
        bash_startup_files = node.get("bash_startup_files")
        if bash_startup_files:
            rendered_files = ", ".join(f"{path}={status}" for path, status in bash_startup_files.items())
            lines.append(f"  Startup files: {rendered_files}")
        prompt_preview = node.get("rendered_prompt_preview")
        if prompt_preview:
            lines.append(f"  Prompt: {prompt_preview}")
        prepared_command = node["prepared"].get("command_text")
        if prepared_command:
            lines.append(f"  Prepared: {prepared_command}")
        launch_command = node["launch"].get("command_text")
        lines.append(f"  Launch: {launch_command or node['launch']['kind']}")
        cwd = node["launch"].get("cwd") or node["prepared"].get("cwd")
        if cwd:
            lines.append(f"  Cwd: {cwd}")
        env_keys = node["launch"].get("env_keys") or node["prepared"].get("env_keys")
        if env_keys:
            lines.append(f"  Env keys: {', '.join(env_keys)}")
        runtime_files = node["launch"].get("runtime_files") or node["prepared"].get("runtime_files")
        if runtime_files:
            lines.append(f"  Runtime files: {', '.join(runtime_files)}")
        payload_summary = node["launch"].get("payload_summary")
        if payload_summary:
            lines.append(f"  Payload: {payload_summary}")
        for warning in node.get("warnings", []):
            lines.append(f"  Warning: {warning}")
        for note in node.get("notes", []):
            lines.append(f"  Note: {note}")
    return "\n".join(lines)
