from __future__ import annotations

import asyncio
import os
import shlex
import traceback
from contextlib import suppress
from dataclasses import dataclass, field
from pathlib import Path
from typing import Awaitable, Callable, Protocol

from pydantic import BaseModel, Field

from agentflow.prepared import ExecutionPaths, PreparedExecution
from agentflow.specs import LocalTarget, NodeSpec
from agentflow.utils import ensure_dir


class RawExecutionResult(BaseModel):
    exit_code: int
    stdout_lines: list[str] = Field(default_factory=list)
    stderr_lines: list[str] = Field(default_factory=list)
    timed_out: bool = False
    cancelled: bool = False


StreamCallback = Callable[[str, str], Awaitable[None]]
CancelCallback = Callable[[], bool]


@dataclass(slots=True)
class LaunchPlan:
    kind: str = "process"
    command: list[str] | None = None
    env: dict[str, str] = field(default_factory=dict)
    cwd: str | None = None
    stdin: str | None = None
    runtime_files: list[str] = field(default_factory=list)
    payload: dict[str, object] | None = None


def default_launch_plan(prepared: PreparedExecution) -> LaunchPlan:
    return LaunchPlan(
        command=list(prepared.command),
        env=dict(prepared.env),
        cwd=prepared.cwd,
        stdin=prepared.stdin,
        runtime_files=sorted(prepared.runtime_files),
    )


def materialize_runtime_files(base_dir: Path, runtime_files: dict[str, str]) -> None:
    for relative_path, content in runtime_files.items():
        target = base_dir / relative_path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")


class Runner(Protocol):
    def plan_execution(
        self,
        node: NodeSpec,
        prepared: PreparedExecution,
        paths: ExecutionPaths,
    ) -> LaunchPlan: ...

    async def execute(
        self,
        node: NodeSpec,
        prepared: PreparedExecution,
        paths: ExecutionPaths,
        on_output: StreamCallback,
        should_cancel: CancelCallback,
    ) -> RawExecutionResult: ...


class LocalRunner:
    _TERMINATE_GRACE_SECONDS = 1.0

    def _command_for_target(self, node: NodeSpec, prepared: PreparedExecution) -> tuple[list[str], dict[str, str]]:
        target = node.target
        if not isinstance(target, LocalTarget):
            return prepared.command, {}

        command_text = shlex.join(prepared.command)
        return ["/bin/bash", "-c", 'eval "$AGENTFLOW_TARGET_COMMAND"'], {"AGENTFLOW_TARGET_COMMAND": command_text}

    def _resolve_launch_plan(
        self,
        node: NodeSpec,
        prepared: PreparedExecution,
        paths: ExecutionPaths,
    ) -> LaunchPlan:
        command, target_env = self._command_for_target(node, prepared)
        env = dict(prepared.env)
        env.update(target_env)
        plan = default_launch_plan(prepared)
        plan.command = command
        plan.env = env
        return plan

    def plan_execution(
        self,
        node: NodeSpec,
        prepared: PreparedExecution,
        paths: ExecutionPaths,
    ) -> LaunchPlan:
        return self._resolve_launch_plan(node, prepared, paths)

    async def _wait_for_exit(self, wait_task: asyncio.Task[int], timeout: float) -> bool:
        if wait_task.done():
            return True
        try:
            await asyncio.wait_for(asyncio.shield(wait_task), timeout=timeout)
        except asyncio.TimeoutError:
            return False
        return True

    async def _terminate_with_fallback(self, process, wait_task: asyncio.Task[int]) -> None:
        with suppress(ProcessLookupError):
            process.terminate()
        if await self._wait_for_exit(wait_task, self._TERMINATE_GRACE_SECONDS):
            return
        with suppress(ProcessLookupError):
            process.kill()
        await self._wait_for_exit(wait_task, self._TERMINATE_GRACE_SECONDS)

    async def _consume_stream(self, stream, stream_name: str, buffer: list[str], on_output: StreamCallback) -> None:
        while True:
            line = await stream.readline()
            if not line:
                break
            text = line.decode("utf-8", errors="replace").rstrip("\n")
            buffer.append(text)
            await on_output(stream_name, text)

    async def execute(
        self,
        node: NodeSpec,
        prepared: PreparedExecution,
        paths: ExecutionPaths,
        on_output: StreamCallback,
        should_cancel: CancelCallback,
    ) -> RawExecutionResult:
        materialize_runtime_files(paths.host_runtime_dir, prepared.runtime_files)
        ensure_dir(Path(prepared.cwd))
        plan = self._resolve_launch_plan(node, prepared, paths)
        env = os.environ.copy()
        env.update(plan.env)
        process = await asyncio.create_subprocess_exec(
            *(plan.command or []),
            cwd=plan.cwd,
            env=env,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            stdin=asyncio.subprocess.PIPE if plan.stdin is not None else asyncio.subprocess.DEVNULL,
        )
        if plan.stdin is not None and process.stdin is not None:
            process.stdin.write(plan.stdin.encode("utf-8"))
            await process.stdin.drain()
            process.stdin.close()
        elif process.stdin is not None:
            process.stdin.close()

        stdout_lines: list[str] = []
        stderr_lines: list[str] = []
        stdout_task = asyncio.create_task(self._consume_stream(process.stdout, "stdout", stdout_lines, on_output))
        stderr_task = asyncio.create_task(self._consume_stream(process.stderr, "stderr", stderr_lines, on_output))
        wait_task = asyncio.create_task(process.wait())
        timed_out = False
        cancelled = False
        execution_error: Exception | None = None

        timeout = node.timeout_seconds if node.timeout_seconds and node.timeout_seconds > 0 else None
        deadline = asyncio.get_running_loop().time() + timeout if timeout else None

        try:
            while True:
                remaining = deadline - asyncio.get_running_loop().time() if deadline else None
                if remaining is not None and remaining <= 0:
                    timed_out = True
                    break
                if should_cancel():
                    cancelled = True
                    break
                check_timeout = min(remaining or 1.0, 1.0)
                done, _ = await asyncio.wait(
                    {stdout_task, stderr_task, wait_task},
                    timeout=check_timeout,
                    return_when=asyncio.FIRST_COMPLETED,
                )
                if wait_task in done:
                    break
                if stdout_task in done and stderr_task in done:
                    if not wait_task.done():
                        try:
                            await asyncio.wait_for(wait_task, timeout=5)
                        except asyncio.TimeoutError:
                            execution_error = RuntimeError("process did not exit after stdout/stderr closed")
                    break
        except Exception as exc:
            execution_error = exc

        async def _drain_streams() -> None:
            try:
                await asyncio.wait_for(
                    asyncio.gather(stdout_task, stderr_task, return_exceptions=True),
                    timeout=3,
                )
            except asyncio.TimeoutError:
                for task in (stdout_task, stderr_task):
                    if not task.done():
                        task.cancel()
                        with suppress(asyncio.CancelledError):
                            await task

        if timed_out:
            await self._terminate_with_fallback(process, wait_task)
            await _drain_streams()
            stderr_lines.append(f"Timed out after {node.timeout_seconds}s")
            await on_output("stderr", stderr_lines[-1])
        elif execution_error is not None:
            await self._terminate_with_fallback(process, wait_task)
            await _drain_streams()
            error_message = "".join(
                traceback.format_exception_only(type(execution_error), execution_error)
            ).strip()
            stderr_lines.append(f"Execution failed: {error_message}")
            await on_output("stderr", stderr_lines[-1])
        elif cancelled:
            await self._terminate_with_fallback(process, wait_task)
            await _drain_streams()
            stderr_lines.append("Cancelled by user")
            await on_output("stderr", stderr_lines[-1])
        else:
            await _drain_streams()
            if not wait_task.done():
                await wait_task

        if timed_out:
            exit_code = 124
        elif cancelled:
            exit_code = 130
        elif execution_error is not None:
            exit_code = process.returncode if process.returncode is not None else 1
        else:
            exit_code = process.returncode if process.returncode is not None else 0
        return RawExecutionResult(
            exit_code=exit_code,
            stdout_lines=stdout_lines,
            stderr_lines=stderr_lines,
            timed_out=timed_out,
            cancelled=cancelled,
        )


__all__ = [
    "CancelCallback",
    "LaunchPlan",
    "LocalRunner",
    "RawExecutionResult",
    "Runner",
    "StreamCallback",
    "default_launch_plan",
    "materialize_runtime_files",
]
