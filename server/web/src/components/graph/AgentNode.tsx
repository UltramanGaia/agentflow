import type { NodeProps } from "reactflow";
import { Handle, Position } from "reactflow";
import { StatusBadge } from "../status/StatusBadge";

export interface AgentNodeData {
  title: string;
  agent: string;
  status?: string;
  subtitle?: string;
  meta?: string;
  onInspect?: () => void;
}

export function AgentNode({ data, selected }: NodeProps<AgentNodeData>) {
  return (
    <div className={`flow-node${selected ? " selected" : ""}`}>
      <Handle type="target" position={Position.Left} />
      <div className="flow-node-head">
        <div className="flow-node-title">{data.title}</div>
        {data.onInspect ? (
          <button
            aria-label={`Inspect ${data.title}`}
            className="icon-button flow-node-icon-button"
            onClick={(event) => {
              event.preventDefault();
              event.stopPropagation();
              data.onInspect?.();
            }}
            type="button"
          >
            <svg aria-hidden="true" className="flow-node-icon" viewBox="0 0 16 16">
              <path
                d="M8 3.25A4.75 4.75 0 1 0 8 12.75A4.75 4.75 0 1 0 8 3.25ZM2 8a6 6 0 1 1 12 0A6 6 0 0 1 2 8Zm5.25-2a.75.75 0 1 1 1.5 0a.75.75 0 0 1-1.5 0ZM7 7.25a.75.75 0 0 1 .75-.75h.5A.75.75 0 0 1 9 7.25v2.5a.75.75 0 0 1-.75.75h-.5a.75.75 0 0 1 0-1.5V7.25H7Z"
                fill="currentColor"
              />
            </svg>
          </button>
        ) : null}
      </div>
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
