"""EC2 runner: launch instance, SSH execute, terminate."""

from __future__ import annotations

import asyncio
import base64
from types import SimpleNamespace

from agentflow.cloud.aws import collect_local_credentials, discover_networking, discover_ubuntu_ami, ensure_key_pair
from agentflow.cloud.installer import agent_auth_setup
from agentflow.cloud.shared import SharedResourceManager
from agentflow.prepared import ExecutionPaths, PreparedExecution
from agentflow.runners.base import (
    CancelCallback,
    LaunchPlan,
    RawExecutionResult,
    Runner,
    StreamCallback,
)
from agentflow.runners.ssh import SSHRunner
from agentflow.specs import NodeSpec, normalize_agent_name


class EC2Runner(Runner):
    """Launch a fresh EC2 instance, execute via SSH, then terminate.

    When the target has ``shared`` set, multiple nodes reuse one instance
    managed by a :class:`SharedResourceManager`.
    """

    _shared_manager: SharedResourceManager | None = None

    def _launch_instance(self, node: NodeSpec, prepared: PreparedExecution) -> str:
        import boto3

        target = node.target
        ec2 = boto3.client("ec2", region_name=target.region)

        params: dict = {
            "ImageId": target.ami,
            "InstanceType": target.instance_type,
            "MinCount": 1,
            "MaxCount": 1,
            "TagSpecifications": [
                {
                    "ResourceType": "instance",
                    "Tags": [{"Key": "Name", "Value": f"agentflow-{node.id}"}],
                }
            ],
        }
        if target.key_name:
            params["KeyName"] = target.key_name
        if target.security_group_ids:
            params["SecurityGroupIds"] = target.security_group_ids
        if target.subnet_id:
            params["SubnetId"] = target.subnet_id

        user_data_parts: list[str] = []
        if target.install_agents:
            from agentflow.cloud.installer import agent_install_script

            user_data_parts.append(agent_install_script(target.install_agents))
        if target.user_data:
            user_data_parts.append(target.user_data)
        if user_data_parts:
            params["UserData"] = base64.b64encode(
                "\n".join(user_data_parts).encode()
            ).decode()

        if target.spot:
            params["InstanceMarketOptions"] = {"MarketType": "spot"}

        response = ec2.run_instances(**params)
        return response["Instances"][0]["InstanceId"]

    def _wait_for_ssh(self, region: str, instance_id: str) -> str:
        import boto3

        ec2 = boto3.client("ec2", region_name=region)
        waiter = ec2.get_waiter("instance_running")
        waiter.wait(InstanceIds=[instance_id], WaiterConfig={"Delay": 5, "MaxAttempts": 60})
        waiter = ec2.get_waiter("instance_status_ok")
        waiter.wait(InstanceIds=[instance_id], WaiterConfig={"Delay": 10, "MaxAttempts": 30})

        response = ec2.describe_instances(InstanceIds=[instance_id])
        instance = response["Reservations"][0]["Instances"][0]
        return instance.get("PublicIpAddress") or instance.get("PrivateIpAddress")

    def _snapshot_instance(self, region: str, instance_id: str, name: str) -> str:
        import boto3

        ec2 = boto3.client("ec2", region_name=region)
        resp = ec2.create_image(
            InstanceId=instance_id,
            Name=name,
            NoReboot=False,
            TagSpecifications=[{
                "ResourceType": "image",
                "Tags": [{"Key": "Name", "Value": name}, {"Key": "CreatedBy", "Value": "agentflow"}],
            }],
        )
        return resp["ImageId"]

    def _terminate_instance(self, region: str, instance_id: str) -> None:
        import boto3

        boto3.client("ec2", region_name=region).terminate_instances(InstanceIds=[instance_id])

    async def _resolve_target(self, target, node, on_output):
        """Auto-discover AMI, key pair, and networking if not specified."""
        needs_patch = False

        if not target.ami:
            await on_output("stderr", f"Finding latest Ubuntu AMI in {target.region}...")
            ami = await asyncio.to_thread(discover_ubuntu_ami, target.region)
            target = SimpleNamespace(**{k: getattr(target, k) for k in target.model_fields})
            target.ami = ami
            needs_patch = True

        if not target.key_name:
            await on_output("stderr", "Ensuring SSH key pair...")
            key_name, identity_file = await asyncio.to_thread(ensure_key_pair, target.region)
            if not needs_patch:
                target = SimpleNamespace(**{k: getattr(target, k) for k in target.model_fields})
                needs_patch = True
            target.key_name = key_name
            target.identity_file = identity_file

        if not target.security_group_ids:
            await on_output("stderr", "Auto-discovering VPC networking...")
            net = await asyncio.to_thread(discover_networking, target.region)
            if not needs_patch:
                target = SimpleNamespace(**{k: getattr(target, k) for k in target.model_fields})
                needs_patch = True
            target.security_group_ids = net["security_groups"]
            if not target.subnet_id:
                target.subnet_id = net["subnets"][0]

        if needs_patch:
            node = SimpleNamespace(id=node.id, agent=node.agent, target=target, timeout_seconds=node.timeout_seconds)
        return target, node

    async def _prepare_env(self, node, prepared):
        """Forward local credentials and build auth setup."""
        local_creds = collect_local_credentials(normalize_agent_name(node.agent))
        merged_env = {**local_creds, **prepared.env}
        return PreparedExecution(
            command=prepared.command, env=merged_env, cwd=prepared.cwd,
            trace_kind=prepared.trace_kind, runtime_files=prepared.runtime_files,
            stdin=prepared.stdin,
        )

    async def _ssh_execute(self, ip, target, node, prepared, paths, on_output, should_cancel):
        """Execute a command on an instance via SSH."""
        import shlex

        ssh_target = SimpleNamespace(
            kind="ssh", host=ip, port=22,
            username=target.username,
            identity_file=target.identity_file,
            remote_workdir=None,
        )
        ssh_runner = SSHRunner()

        # Wait for cloud-init if agents are being installed
        if target.install_agents:
            await on_output("stderr", "Waiting for agent installation (cloud-init)...")
            wait_node = SimpleNamespace(id=node.id, target=ssh_target, timeout_seconds=600)
            wait_prepared = PreparedExecution(
                command=["cloud-init", "status", "--wait"],
                env={}, cwd="/tmp", trace_kind="setup", runtime_files={}, stdin=None,
            )
            wait_result = await ssh_runner.execute(
                wait_node, wait_prepared, paths,
                lambda s, l: on_output("stderr", f"  [cloud-init] {l}"),
                should_cancel,
            )
            if wait_result.exit_code != 0:
                await on_output("stderr", "cloud-init may have failed, proceeding anyway...")

        # Inject agent auth setup
        auth_setup = agent_auth_setup(normalize_agent_name(node.agent), prepared.env)
        if auth_setup:
            original_cmd = " ".join(shlex.quote(p) for p in prepared.command)
            auth_prepared = PreparedExecution(
                command=["bash", "-c", f"{auth_setup} && {original_cmd}"],
                env=prepared.env, cwd=prepared.cwd, trace_kind=prepared.trace_kind,
                runtime_files=prepared.runtime_files, stdin=prepared.stdin,
            )
        else:
            auth_prepared = prepared

        await on_output("stderr", "Executing agent command...")
        ssh_node = SimpleNamespace(id=node.id, target=ssh_target, timeout_seconds=node.timeout_seconds)
        return await ssh_runner.execute(ssh_node, auth_prepared, paths, on_output, should_cancel)

    def plan_execution(self, node, prepared, paths):
        target = node.target
        return LaunchPlan(
            kind="ec2",
            command=prepared.command,
            env=prepared.env,
            cwd=str(paths.target_workdir),
            payload={
                "ami": target.ami,
                "instance_type": target.instance_type,
                "region": target.region,
                "spot": getattr(target, "spot", False),
                "shared": getattr(target, "shared", None),
            },
        )

    async def execute(
        self,
        node: NodeSpec,
        prepared: PreparedExecution,
        paths: ExecutionPaths,
        on_output: StreamCallback,
        should_cancel: CancelCallback,
    ) -> RawExecutionResult:
        target = node.target
        if should_cancel():
            return RawExecutionResult(exit_code=130, stdout_lines=[], stderr_lines=["Cancelled"], timed_out=False, cancelled=True)

        try:
            target, node = await self._resolve_target(target, node, on_output)
            prepared = await self._prepare_env(node, prepared)
        except Exception as exc:
            return RawExecutionResult(exit_code=1, stdout_lines=[], stderr_lines=[f"EC2 setup failed: {exc}"], timed_out=False, cancelled=False)

        shared_id = getattr(target, "shared", None)

        # -- Shared instance path --
        if shared_id and self._shared_manager:
            try:
                ip, instance_id = await self._shared_manager.acquire_ec2(
                    shared_id, target, node, prepared, on_output,
                    self._launch_instance, self._wait_for_ssh,
                )
                return await self._ssh_execute(ip, target, node, prepared, paths, on_output, should_cancel)
            except Exception as exc:
                return RawExecutionResult(exit_code=1, stdout_lines=[], stderr_lines=[f"EC2 execution failed: {exc}"], timed_out=False, cancelled=False)
            finally:
                await self._shared_manager.release_ec2(
                    shared_id, target, on_output,
                    self._terminate_instance, self._snapshot_instance,
                )

        # -- Per-node instance path --
        instance_id: str | None = None
        try:
            await on_output("stderr", f"Launching EC2 {target.instance_type} ({target.ami})...")
            instance_id = await asyncio.to_thread(self._launch_instance, node, prepared)
            await on_output("stderr", f"Instance {instance_id} launched, waiting for SSH...")

            ip = await asyncio.to_thread(self._wait_for_ssh, target.region, instance_id)
            await on_output("stderr", f"Instance ready at {ip}")

            return await self._ssh_execute(ip, target, node, prepared, paths, on_output, should_cancel)
        except Exception as exc:
            return RawExecutionResult(exit_code=1, stdout_lines=[], stderr_lines=[f"EC2 execution failed: {exc}"], timed_out=False, cancelled=False)
        finally:
            if instance_id:
                try:
                    if getattr(target, "snapshot", False):
                        snap_name = f"agentflow-{node.id}-{instance_id}"
                        await on_output("stderr", f"Creating snapshot {snap_name}...")
                        ami_id = await asyncio.to_thread(self._snapshot_instance, target.region, instance_id, snap_name)
                        await on_output("stderr", f"Snapshot AMI: {ami_id}")
                    if getattr(target, "terminate", True):
                        await on_output("stderr", f"Terminating {instance_id}...")
                        await asyncio.to_thread(self._terminate_instance, target.region, instance_id)
                        await on_output("stderr", f"Instance {instance_id} terminated.")
                    else:
                        await on_output("stderr", f"Instance {instance_id} left running (terminate=false).")
                except Exception as exc:
                    await on_output("stderr", f"Warning: cleanup failed for {instance_id}: {exc}")
