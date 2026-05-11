import { Position, type Node } from "reactflow";
import type { RunNode } from "../../types/api";

const NODE_WIDTH = 220;
const NODE_HEIGHT = 152;
const COLUMN_GAP = 120;
const ROW_GAP = 44;
const PADDING_X = 80;
const PADDING_Y = 80;

export interface RuntimeGraphNode {
  id: string;
  title: string;
  agent: string;
  status: string;
  depends_on: string[];
  memberNodeIds: string[];
  subtitle?: string;
  meta?: string;
}

export interface RuntimeGraphEdge {
  id: string;
  source: string;
  target: string;
}

export interface RuntimeGraphModel {
  nodes: RuntimeGraphNode[];
  edges: RuntimeGraphEdge[];
}

export function buildRunLayout(
  graphNodes: RuntimeGraphNode[],
  handlers?: {
    onInspect?: (nodeId: string) => void;
  },
): Node[] {
  const nodeById = new Map(graphNodes.map((node) => [node.id, node]));
  const layerById = new Map<string, number>();
  const indegree = new Map<string, number>();
  const downstream = new Map<string, string[]>();
  const order = new Map(graphNodes.map((node, index) => [node.id, index]));

  graphNodes.forEach((node) => {
    indegree.set(node.id, 0);
    downstream.set(node.id, []);
  });

  graphNodes.forEach((node) => {
    node.depends_on.forEach((dependency) => {
      if (!nodeById.has(dependency)) {
        return;
      }
      indegree.set(node.id, (indegree.get(node.id) ?? 0) + 1);
      downstream.get(dependency)?.push(node.id);
    });
  });

  const queue = graphNodes
    .filter((node) => (indegree.get(node.id) ?? 0) === 0)
    .sort((left, right) => (order.get(left.id) ?? 0) - (order.get(right.id) ?? 0))
    .map((node) => node.id);
  const topoOrder: string[] = [];

  while (queue.length > 0) {
    const currentId = queue.shift()!;
    topoOrder.push(currentId);
    const currentLayer = layerById.get(currentId) ?? 0;
    for (const nextId of downstream.get(currentId) ?? []) {
      layerById.set(nextId, Math.max(layerById.get(nextId) ?? 0, currentLayer + 1));
      indegree.set(nextId, (indegree.get(nextId) ?? 1) - 1);
      if ((indegree.get(nextId) ?? 0) === 0) {
        queue.push(nextId);
        queue.sort((left, right) => (order.get(left) ?? 0) - (order.get(right) ?? 0));
      }
    }
  }

  const remainingIds = graphNodes
    .map((node) => node.id)
    .filter((nodeId) => !topoOrder.includes(nodeId))
    .sort((left, right) => (order.get(left) ?? 0) - (order.get(right) ?? 0));
  topoOrder.push(...remainingIds);

  remainingIds.forEach((nodeId) => {
    const node = nodeById.get(nodeId);
    if (!node) {
      return;
    }
    const inferredLayer = node.depends_on.reduce((maxLayer, dependency) => {
      return Math.max(maxLayer, (layerById.get(dependency) ?? -1) + 1);
    }, 0);
    layerById.set(nodeId, Math.max(layerById.get(nodeId) ?? 0, inferredLayer));
  });

  const columns = new Map<number, string[]>();
  topoOrder.forEach((nodeId) => {
    const layer = layerById.get(nodeId) ?? 0;
    const nodesInColumn = columns.get(layer) ?? [];
    nodesInColumn.push(nodeId);
    columns.set(layer, nodesInColumn);
  });

  const maxColumnSize = Math.max(...Array.from(columns.values(), (column) => column.length), 1);

  return graphNodes.map<Node>((node) => {
    const layer = layerById.get(node.id) ?? 0;
    const row = columns.get(layer)?.indexOf(node.id) ?? 0;
    const columnSize = columns.get(layer)?.length ?? 1;
    const verticalOffset = ((maxColumnSize - columnSize) * (NODE_HEIGHT + ROW_GAP)) / 2;

    return {
      id: node.id,
      type: "agentNode",
      position: {
        x: PADDING_X + layer * (NODE_WIDTH + COLUMN_GAP),
        y: PADDING_Y + verticalOffset + row * (NODE_HEIGHT + ROW_GAP),
      },
      sourcePosition: Position.Right,
      targetPosition: Position.Left,
      data: {
        title: node.title,
        agent: node.agent,
        status: node.status,
        subtitle: node.subtitle,
        meta: node.meta,
        onInspect: handlers?.onInspect ? () => handlers.onInspect?.(node.id) : undefined,
      },
      selected: false,
    };
  });
}

function aggregateStatus(statuses: string[]): string {
  const rank: Record<string, number> = {
    failed: 0,
    cancelled: 1,
    cancelling: 2,
    running: 3,
    pending: 4,
    queued: 5,
    ready: 6,
    completed: 7,
  };
  return [...statuses].sort((left, right) => (rank[left] ?? 999) - (rank[right] ?? 999))[0] ?? "pending";
}

export function buildInstanceGraph(runNodes: RunNode[]): RuntimeGraphModel {
  return {
    nodes: runNodes.map((node) => {
      const metaParts: string[] = [];
      if (node.attempts.length > 1) {
        metaParts.push(`${node.attempts.length} attempts`);
      }
      if (node.tick_count > 0) {
        metaParts.push(`${node.tick_count} ticks`);
      }
      return {
        id: node.id,
        title: node.id,
        agent: node.agent,
        status: node.status,
        depends_on: node.depends_on,
        memberNodeIds: [node.id],
        subtitle: node.fanout_group ? `fanout · ${node.fanout_group}` : undefined,
        meta: metaParts.length ? metaParts.join(" · ") : undefined,
      };
    }),
    edges: runNodes.flatMap((node) =>
      node.depends_on.map((dependency) => ({
        id: `${dependency}->${node.id}`,
        source: dependency,
        target: node.id,
      })),
    ),
  };
}

export function buildStageGraph(runNodes: RunNode[]): RuntimeGraphModel {
  const nodeToGroup = new Map<string, string>();
  const groupMembers = new Map<string, RunNode[]>();

  runNodes.forEach((node) => {
    const groupId = node.fanout_group ?? node.id;
    nodeToGroup.set(node.id, groupId);
    const members = groupMembers.get(groupId) ?? [];
    members.push(node);
    groupMembers.set(groupId, members);
  });

  const groupOrder = Array.from(groupMembers.keys()).sort((left, right) => {
    const leftIndex = runNodes.findIndex((node) => (node.fanout_group ?? node.id) === left);
    const rightIndex = runNodes.findIndex((node) => (node.fanout_group ?? node.id) === right);
    return leftIndex - rightIndex;
  });

  const edgeMap = new Map<string, RuntimeGraphEdge>();
  runNodes.forEach((node) => {
    const targetGroup = nodeToGroup.get(node.id) ?? node.id;
    node.depends_on.forEach((dependency) => {
      const sourceGroup = nodeToGroup.get(dependency) ?? dependency;
      if (sourceGroup === targetGroup) {
        return;
      }
      edgeMap.set(`${sourceGroup}->${targetGroup}`, {
        id: `${sourceGroup}->${targetGroup}`,
        source: sourceGroup,
        target: targetGroup,
      });
    });
  });

  return {
    nodes: groupOrder.map((groupId) => {
      const members = groupMembers.get(groupId) ?? [];
      const totalAttempts = members.reduce((sum, node) => sum + Math.max(node.attempts.length, 1), 0);
      const totalTicks = members.reduce((sum, node) => sum + node.tick_count, 0);
      const metaParts: string[] = [];
      if (totalAttempts > members.length) {
        metaParts.push(`${totalAttempts} attempts`);
      }
      if (totalTicks > 0) {
        metaParts.push(`${totalTicks} ticks`);
      }
      return {
        id: groupId,
        title: groupId,
        agent: Array.from(new Set(members.map((node) => node.agent))).join(", "),
        status: aggregateStatus(members.map((node) => node.status)),
        depends_on: Array.from(
          new Set(
            members.flatMap((node) =>
              node.depends_on
                .map((dependency) => nodeToGroup.get(dependency) ?? dependency)
                .filter((dependency) => dependency !== groupId),
            ),
          ),
        ),
        memberNodeIds: members.map((node) => node.id),
        subtitle: members.length > 1 ? `${members.length} instances` : "1 instance",
        meta: metaParts.length ? metaParts.join(" · ") : undefined,
      };
    }),
    edges: Array.from(edgeMap.values()),
  };
}

export function chooseDefaultNodeId(nodes: RunNode[]) {
  return nodes.find((node) => node.status === "failed")?.id ??
    nodes.find((node) => node.status === "running")?.id ??
    nodes[0]?.id ??
    null;
}

export function chooseDefaultGraphNodeId(nodes: RuntimeGraphNode[]) {
  return nodes.find((node) => node.status === "failed")?.id ??
    nodes.find((node) => node.status === "running")?.id ??
    nodes[0]?.id ??
    null;
}
