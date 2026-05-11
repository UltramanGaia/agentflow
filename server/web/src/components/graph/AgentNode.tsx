import type { NodeProps } from "reactflow";
import { Handle, Position } from "reactflow";
import { StatusBadge } from "../status/StatusBadge";

export interface AgentNodeData {
  title: string;
  agent: string;
  status?: string;
  subtitle?: string;
  meta?: string;
}

export function AgentNode({ data, selected }: NodeProps<AgentNodeData>) {
  return (
    <div className={`flow-node${selected ? " selected" : ""}`}>
      <Handle type="target" position={Position.Left} />
      <div className="flow-node-title">{data.title}</div>
      <div className="flow-node-agent">{data.agent}</div>
      {data.subtitle ? <div className="flow-node-subtitle">{data.subtitle}</div> : null}
      {data.meta ? <div className="flow-node-meta">{data.meta}</div> : null}
      {data.status ? (
        <div className="flow-node-status">
          <StatusBadge status={data.status} />
        </div>
      ) : null}
      <Handle type="source" position={Position.Right} />
    </div>
  );
}
