const app = document.getElementById("app");

const state = {
  graphs: [],
  runs: [],
  currentRun: null,
  currentGraph: null,
  selectedNodeId: null,
  activeRunTab: "overview",
  jsonMode: false,
  exportContent: "",
};

function api(path, options = {}) {
  const headers = { "Content-Type": "application/json", ...(options.headers || {}) };
  return fetch(path, { ...options, headers }).then(async (response) => {
    if (!response.ok) {
      const payload = await response.json().catch(() => ({}));
      throw new Error(payload.detail || `Request failed: ${response.status}`);
    }
    const contentType = response.headers.get("content-type") || "";
    return contentType.includes("application/json") ? response.json() : response.text();
  });
}

function navigate(path) {
  history.pushState({}, "", path);
  render();
}

window.addEventListener("popstate", render);

function statusPill(status) {
  return `<span class="pill status-${status}">${status}</span>`;
}

function shell(content) {
  app.innerHTML = `
    <div class="shell">
      <div class="topbar">
        <div class="brand">AgentFlow<small>server control plane</small></div>
        <div class="nav">
          <a href="/runs" data-link>Runs</a>
          <a href="/graphs/new/edit" data-link>New Graph</a>
        </div>
      </div>
      ${content}
    </div>
  `;
  app.querySelectorAll("[data-link]").forEach((node) => {
    node.addEventListener("click", (event) => {
      event.preventDefault();
      navigate(node.getAttribute("href"));
    });
  });
}

function defaultGraph() {
  return {
    meta: { id: "new", name: "new-graph", description: "", layout: {} },
    pipeline: {
      name: "new-graph",
      description: "",
      working_dir: ".",
      concurrency: 4,
      fail_fast: false,
      max_iterations: 10,
      scratchboard: false,
      use_worktree: false,
      nodes: [],
    },
  };
}

function ensureLayout(graph) {
  const layout = graph.meta.layout || {};
  graph.pipeline.nodes.forEach((node, index) => {
    if (!layout[node.id]) {
      layout[node.id] = { x: 60 + (index % 3) * 240, y: 50 + Math.floor(index / 3) * 140 };
    }
  });
  graph.meta.layout = layout;
}

function pipelineEdges(pipeline) {
  return pipeline.nodes.flatMap((node) => node.depends_on.map((dep) => ({ source: dep, target: node.id })));
}

function renderDag(graph, { statuses = {} } = {}) {
  ensureLayout(graph);
  const layout = graph.meta.layout;
  const edges = pipelineEdges(graph.pipeline);
  const svg = edges.map((edge) => {
    const from = layout[edge.source] || { x: 0, y: 0 };
    const to = layout[edge.target] || { x: 0, y: 0 };
    return `<line x1="${from.x + 180}" y1="${from.y + 46}" x2="${to.x}" y2="${to.y + 46}" stroke="#8d7557" stroke-width="2" />`;
  }).join("");
  const nodes = graph.pipeline.nodes.map((node) => {
    const pos = layout[node.id];
    const selected = state.selectedNodeId === node.id ? "selected" : "";
    const status = statuses[node.id] || "pending";
    return `
      <div class="node ${selected}" data-node-id="${node.id}" style="left:${pos.x}px;top:${pos.y}px;">
        <div class="title">${node.id}</div>
        <div class="agent">${node.agent}</div>
        <div class="muted">${status}</div>
      </div>
    `;
  }).join("");
  return `<div class="dag"><svg>${svg}</svg>${nodes}</div>`;
}

async function loadRuns() {
  state.runs = await api("/api/runs");
}

async function loadGraphs() {
  state.graphs = await api("/api/graphs");
}

async function renderRunsPage() {
  await Promise.all([loadRuns(), loadGraphs()]);
  const graphLinks = state.graphs.slice(0, 5).map((graph) => (
    `<div class="list-item"><a href="/graphs/${graph.id}/edit" data-link>${graph.name}</a><div class="muted">${graph.node_count} nodes</div></div>`
  )).join("");
  const runs = state.runs.map((run) => `
    <div class="list-item">
      <a href="/runs/${run.id}" data-link><strong>${run.pipeline_name}</strong></a>
      <div class="muted">${run.id}</div>
      <div style="margin-top:8px; display:flex; gap:8px; align-items:center; flex-wrap:wrap;">
        ${statusPill(run.status)}
        <span class="muted">${run.node_count} nodes</span>
        <span class="muted">${run.failed_nodes.length ? `failed: ${run.failed_nodes.join(", ")}` : "no failed nodes"}</span>
      </div>
    </div>
  `).join("");
  shell(`
    <div class="layout">
      <div class="panel">
        <h2>Runs</h2>
        <div class="list">${runs || '<div class="muted">No runs yet.</div>'}</div>
      </div>
      <div class="panel">
        <h2>Graphs</h2>
        <div class="toolbar">
          <button class="button primary" id="new-graph">Create Graph</button>
        </div>
        <div class="list">${graphLinks || '<div class="muted">No graphs saved.</div>'}</div>
      </div>
    </div>
  `);
  document.getElementById("new-graph").addEventListener("click", async () => {
    const created = await api("/api/graphs", { method: "POST", body: JSON.stringify({ pipeline: defaultGraph().pipeline, layout: {} }) });
    navigate(`/graphs/${created.meta.id}/edit`);
  });
}

function runStatuses(detail) {
  return Object.fromEntries(detail.graph.nodes.map((node) => [node.id, node.status]));
}

async function loadArtifactText(runId, node, name) {
  if (!node || !node.artifacts.some((artifact) => artifact.name === name)) {
    return "No data.";
  }
  return fetch(`/api/runs/${runId}/nodes/${node.id}/artifacts/${name}`).then((response) => response.text());
}

let currentEventSource = null;

function subscribeRun(runId) {
  if (currentEventSource) {
    currentEventSource.close();
  }
  currentEventSource = new EventSource(`/api/runs/${runId}/stream`);
  currentEventSource.addEventListener("event", () => {
    clearTimeout(subscribeRun.refreshTimer);
    subscribeRun.refreshTimer = setTimeout(() => renderRunPage(runId), 150);
  });
}

async function renderRunPage(runId) {
  state.currentRun = await api(`/api/runs/${runId}`);
  const detail = state.currentRun;
  if (!state.selectedNodeId && detail.graph.nodes[0]) {
    state.selectedNodeId = detail.graph.nodes[0].id;
  }
  const graph = {
    meta: {
      id: runId,
      layout: Object.fromEntries(detail.graph.nodes.map((node, index) => [node.id, { x: 60 + (index % 3) * 240, y: 50 + Math.floor(index / 3) * 140 }])),
    },
    pipeline: { nodes: detail.graph.nodes.map((node) => ({ id: node.id, agent: node.agent, depends_on: node.depends_on })) },
  };
  const selectedNode = detail.graph.nodes.find((node) => node.id === state.selectedNodeId) || detail.graph.nodes[0] || null;
  const artifacts = selectedNode ? selectedNode.artifacts.map((artifact) => (
    `<div class="artifact-row"><a href="/api/runs/${runId}/nodes/${selectedNode.id}/artifacts/${artifact.name}" target="_blank">${artifact.name}</a> <span class="muted">${artifact.size} bytes</span></div>`
  )).join("") : "";
  const eventRows = detail.events.slice(-100).map((event) => `
    <div class="event-row">
      <strong>${event.type}</strong>
      <div class="muted">${event.timestamp}${event.node_id ? ` · ${event.node_id}` : ""}</div>
      <pre>${escapeHtml(JSON.stringify(event.data || {}, null, 2))}</pre>
    </div>
  `).join("");
  const nodeList = detail.graph.nodes.map((node) => `
    <div class="list-item">
      <div style="display:flex;justify-content:space-between;gap:12px;align-items:center;">
        <button class="button" data-select-node="${node.id}">${node.id}</button>
        ${statusPill(node.status)}
      </div>
      <div class="muted" style="margin-top:8px;">${node.agent}</div>
      <div style="margin-top:8px;display:flex;gap:8px;flex-wrap:wrap;">
        <button class="button" data-rerun-node="${node.id}">Rerun Node</button>
      </div>
    </div>
  `).join("");
  shell(`
    <div class="layout">
      <div class="panel stack">
        <div style="display:flex;justify-content:space-between;gap:12px;flex-wrap:wrap;align-items:center;">
          <div>
            <h2>${detail.run.pipeline.name}</h2>
            <div class="muted">${runId}</div>
          </div>
          <div class="toolbar">
            ${statusPill(detail.run.status)}
            <button class="button danger" id="cancel-run">Cancel</button>
            <button class="button" id="resume-run">Resume</button>
            <button class="button" id="rerun-run">Rerun Run</button>
          </div>
        </div>
        ${renderDag(graph, { statuses: runStatuses(detail) })}
      </div>
      <div class="panel stack">
        <div class="tabs">
          <button class="tab ${state.activeRunTab === "overview" ? "active" : ""}" data-tab="overview">Overview</button>
          <button class="tab ${state.activeRunTab === "events" ? "active" : ""}" data-tab="events">Trace</button>
          <button class="tab ${state.activeRunTab === "stdout" ? "active" : ""}" data-tab="stdout">Stdout</button>
          <button class="tab ${state.activeRunTab === "stderr" ? "active" : ""}" data-tab="stderr">Stderr</button>
          <button class="tab ${state.activeRunTab === "artifacts" ? "active" : ""}" data-tab="artifacts">Artifacts</button>
        </div>
        ${state.activeRunTab === "overview" ? `<div class="list">${nodeList}</div>` : ""}
        ${state.activeRunTab === "events" ? `<div class="event-list">${eventRows || '<div class="muted">No events.</div>'}</div>` : ""}
        ${state.activeRunTab === "stdout" ? `<pre>${escapeHtml(await loadArtifactText(runId, selectedNode, "stdout.log"))}</pre>` : ""}
        ${state.activeRunTab === "stderr" ? `<pre>${escapeHtml(await loadArtifactText(runId, selectedNode, "stderr.log"))}</pre>` : ""}
        ${state.activeRunTab === "artifacts" ? `<div class="artifact-list">${artifacts || '<div class="muted">No artifacts.</div>'}</div>` : ""}
      </div>
    </div>
  `);
  app.querySelectorAll("[data-select-node]").forEach((button) => button.addEventListener("click", () => {
    state.selectedNodeId = button.dataset.selectNode;
    renderRunPage(runId);
  }));
  app.querySelectorAll("[data-rerun-node]").forEach((button) => button.addEventListener("click", async () => {
    const response = await api(`/api/runs/${runId}/rerun-node/${button.dataset.rerunNode}`, { method: "POST", body: "{}" });
    navigate(`/runs/${response.redirected_run_id || response.run.id}`);
  }));
  app.querySelectorAll("[data-tab]").forEach((button) => button.addEventListener("click", () => {
    state.activeRunTab = button.dataset.tab;
    renderRunPage(runId);
  }));
  app.querySelectorAll(".node").forEach((node) => node.addEventListener("click", () => {
    state.selectedNodeId = node.dataset.nodeId;
    renderRunPage(runId);
  }));
  document.getElementById("cancel-run").addEventListener("click", async () => {
    await api(`/api/runs/${runId}/cancel`, { method: "POST", body: "{}" });
    renderRunPage(runId);
  });
  document.getElementById("resume-run").addEventListener("click", async () => {
    const response = await api(`/api/runs/${runId}/resume`, { method: "POST", body: "{}" });
    navigate(`/runs/${response.redirected_run_id || response.run.id}`);
  });
  document.getElementById("rerun-run").addEventListener("click", async () => {
    const response = await api(`/api/runs/${runId}/rerun`, { method: "POST", body: "{}" });
    navigate(`/runs/${response.redirected_run_id || response.run.id}`);
  });
  subscribeRun(runId);
}

async function loadGraph(graphId) {
  state.currentGraph = graphId === "new" ? defaultGraph() : await api(`/api/graphs/${graphId}`);
  ensureLayout(state.currentGraph);
  if (!state.selectedNodeId && state.currentGraph.pipeline.nodes[0]) {
    state.selectedNodeId = state.currentGraph.pipeline.nodes[0].id;
  }
}

function syncGraphForm() {
  if (!state.currentGraph) {
    return;
  }
  if (state.jsonMode) {
    state.currentGraph.pipeline = JSON.parse(document.getElementById("pipeline-json").value);
    ensureLayout(state.currentGraph);
    return;
  }
  state.currentGraph.pipeline.name = document.getElementById("graph-name").value;
  state.currentGraph.pipeline.description = document.getElementById("graph-description").value;
  const selectedNode = state.currentGraph.pipeline.nodes.find((node) => node.id === state.selectedNodeId);
  if (!selectedNode) {
    return;
  }
  const oldId = selectedNode.id;
  const parsed = JSON.parse(document.getElementById("node-json").value);
  Object.assign(selectedNode, parsed);
  selectedNode.id = document.getElementById("node-id").value;
  selectedNode.agent = document.getElementById("node-agent").value;
  selectedNode.prompt = document.getElementById("node-prompt").value;
  selectedNode.fanout = parseMaybeJson(document.getElementById("node-fanout").value);
  selectedNode.schedule = parseMaybeJson(document.getElementById("node-schedule").value);
  selectedNode.success_criteria = parseMaybeJson(document.getElementById("node-success-criteria").value) || [];
  if (selectedNode.fanout === null) {
    delete selectedNode.fanout;
  }
  if (selectedNode.schedule === null) {
    delete selectedNode.schedule;
  }
  if (!selectedNode.success_criteria.length) {
    delete selectedNode.success_criteria;
  }
  if (selectedNode.id !== oldId) {
    if (state.currentGraph.meta.layout[oldId]) {
      state.currentGraph.meta.layout[selectedNode.id] = state.currentGraph.meta.layout[oldId];
      delete state.currentGraph.meta.layout[oldId];
    }
    state.currentGraph.pipeline.nodes.forEach((node) => {
      node.depends_on = (node.depends_on || []).map((dep) => dep === oldId ? selectedNode.id : dep);
    });
    state.selectedNodeId = selectedNode.id;
  }
}

function enableDrag(node, graphId) {
  let start = null;
  node.addEventListener("pointerdown", (event) => {
    start = {
      id: node.dataset.nodeId,
      x: event.clientX,
      y: event.clientY,
      original: { ...state.currentGraph.meta.layout[node.dataset.nodeId] },
    };
    node.setPointerCapture(event.pointerId);
  });
  node.addEventListener("pointermove", (event) => {
    if (!start) {
      return;
    }
    const dx = event.clientX - start.x;
    const dy = event.clientY - start.y;
    const next = {
      x: Math.max(10, start.original.x + dx),
      y: Math.max(10, start.original.y + dy),
    };
    state.currentGraph.meta.layout[start.id] = next;
    node.style.left = `${next.x}px`;
    node.style.top = `${next.y}px`;
  });
  node.addEventListener("pointerup", () => {
    start = null;
    renderGraphPage(graphId);
  });
}

async function renderGraphPage(graphId) {
  await loadGraph(graphId);
  const graph = state.currentGraph;
  const selectedNode = graph.pipeline.nodes.find((node) => node.id === state.selectedNodeId) || null;
  const edgeRows = pipelineEdges(graph.pipeline).map((edge) => (
    `<div class="edge-row">${edge.source} → ${edge.target} <button class="button" data-remove-edge="${edge.source}|${edge.target}">Remove</button></div>`
  )).join("");
  shell(`
    <div class="layout">
      <div class="panel stack">
        <div style="display:flex;justify-content:space-between;gap:12px;flex-wrap:wrap;align-items:center;">
          <div>
            <h2>${graph.pipeline.name}</h2>
            <div class="muted">${graph.meta.id}</div>
          </div>
          <div class="toolbar">
            <button class="button primary" id="save-graph">Save</button>
            <button class="button" id="validate-graph">Validate</button>
            <button class="button" id="run-graph">Run</button>
            <button class="button" id="toggle-json">${state.jsonMode ? "Inspector Mode" : "JSON Mode"}</button>
          </div>
        </div>
        ${renderDag(graph)}
        <div class="toolbar">
          <button class="button" id="add-node">Add Node</button>
          <button class="button" id="import-graph">Import Python/JSON/YAML</button>
          <button class="button" id="export-python">Export Python</button>
        </div>
        ${state.exportContent ? `<pre>${escapeHtml(state.exportContent)}</pre>` : ""}
      </div>
      <div class="panel stack">
        ${state.jsonMode ? `
          <div class="field">
            <label>Pipeline JSON</label>
            <textarea id="pipeline-json">${escapeHtml(JSON.stringify(graph.pipeline, null, 2))}</textarea>
          </div>
        ` : `
          <div class="field">
            <label>Graph Name</label>
            <input id="graph-name" value="${escapeAttr(graph.pipeline.name)}">
          </div>
          <div class="field">
            <label>Description</label>
            <textarea id="graph-description">${escapeHtml(graph.pipeline.description || "")}</textarea>
          </div>
          ${selectedNode ? `
            <div class="field">
              <label>Selected Node</label>
              <input id="node-id" value="${escapeAttr(selectedNode.id)}">
            </div>
            <div class="field">
              <label>Agent</label>
              <input id="node-agent" value="${escapeAttr(selectedNode.agent)}">
            </div>
            <div class="field">
              <label>Prompt</label>
              <textarea id="node-prompt">${escapeHtml(selectedNode.prompt || "")}</textarea>
            </div>
            <div class="field">
              <label>Fanout JSON</label>
              <textarea id="node-fanout">${escapeHtml(JSON.stringify(selectedNode.fanout || null, null, 2))}</textarea>
            </div>
            <div class="field">
              <label>Periodic JSON</label>
              <textarea id="node-schedule">${escapeHtml(JSON.stringify(selectedNode.schedule || null, null, 2))}</textarea>
            </div>
            <div class="field">
              <label>Success Criteria JSON</label>
              <textarea id="node-success-criteria">${escapeHtml(JSON.stringify(selectedNode.success_criteria || [], null, 2))}</textarea>
            </div>
            <div class="field">
              <label>Advanced JSON</label>
              <textarea id="node-json">${escapeHtml(JSON.stringify(selectedNode, null, 2))}</textarea>
            </div>
            <div class="grid2">
              <div class="field">
                <label>Connect From</label>
                <select id="edge-source">${graph.pipeline.nodes.map((node) => `<option value="${node.id}">${node.id}</option>`).join("")}</select>
              </div>
              <div class="field">
                <label>Connect To</label>
                <select id="edge-target">${graph.pipeline.nodes.map((node) => `<option value="${node.id}">${node.id}</option>`).join("")}</select>
              </div>
            </div>
            <button class="button" id="add-edge">Add Edge</button>
            <button class="button danger" id="remove-node">Remove Node</button>
            <div class="edge-list">${edgeRows || '<div class="muted">No edges.</div>'}</div>
          ` : '<div class="muted">Select a node to edit it.</div>'}
        `}
      </div>
    </div>
  `);
  app.querySelectorAll(".node").forEach((node) => {
    node.addEventListener("click", () => {
      state.selectedNodeId = node.dataset.nodeId;
      renderGraphPage(graphId);
    });
    enableDrag(node, graphId);
  });
  document.getElementById("save-graph").addEventListener("click", async () => {
    syncGraphForm();
    const method = graphId === "new" ? "POST" : "PUT";
    const path = graphId === "new" ? "/api/graphs" : `/api/graphs/${graphId}`;
    const response = await api(path, {
      method,
      body: JSON.stringify({
        graph_id: graphId === "new" ? undefined : graphId,
        pipeline: state.currentGraph.pipeline,
        layout: state.currentGraph.meta.layout,
      }),
    });
    navigate(`/graphs/${response.meta.id}/edit`);
  });
  document.getElementById("validate-graph").addEventListener("click", async () => {
    syncGraphForm();
    await api("/api/graphs/validate", { method: "POST", body: JSON.stringify({ pipeline: state.currentGraph.pipeline }) });
    alert("PipelineSpec validation passed.");
  });
  document.getElementById("run-graph").addEventListener("click", async () => {
    syncGraphForm();
    const response = await api("/api/runs", { method: "POST", body: JSON.stringify({ pipeline: state.currentGraph.pipeline }) });
    navigate(`/runs/${response.run.id}`);
  });
  document.getElementById("toggle-json").addEventListener("click", () => {
    state.jsonMode = !state.jsonMode;
    renderGraphPage(graphId);
  });
  document.getElementById("add-node").addEventListener("click", () => {
    const nextId = `node_${state.currentGraph.pipeline.nodes.length + 1}`;
    state.currentGraph.pipeline.nodes.push({ id: nextId, agent: "codex", prompt: "", depends_on: [] });
    state.currentGraph.meta.layout[nextId] = { x: 60, y: 60 };
    state.selectedNodeId = nextId;
    renderGraphPage(graphId);
  });
  document.getElementById("import-graph").addEventListener("click", async () => {
    const path = prompt("Pipeline path to import");
    if (!path) {
      return;
    }
    const payload = await api("/api/graphs/import", { method: "POST", body: JSON.stringify({ path }) });
    state.currentGraph.pipeline = payload.pipeline;
    state.currentGraph.meta.layout = {};
    ensureLayout(state.currentGraph);
    renderGraphPage(graphId);
  });
  document.getElementById("export-python").addEventListener("click", async () => {
    if (graphId === "new") {
      alert("Save the graph before exporting.");
      return;
    }
    const payload = await api(`/api/graphs/${graphId}/export/python`);
    state.exportContent = payload.content;
    renderGraphPage(graphId);
  });
  if (document.getElementById("add-edge")) {
    document.getElementById("add-edge").addEventListener("click", () => {
      const source = document.getElementById("edge-source").value;
      const target = document.getElementById("edge-target").value;
      if (!source || !target || source === target) {
        return;
      }
      const node = state.currentGraph.pipeline.nodes.find((item) => item.id === target);
      if (node && !node.depends_on.includes(source)) {
        node.depends_on.push(source);
      }
      renderGraphPage(graphId);
    });
  }
  if (document.getElementById("remove-node")) {
    document.getElementById("remove-node").addEventListener("click", () => {
      const removeId = state.selectedNodeId;
      state.currentGraph.pipeline.nodes = state.currentGraph.pipeline.nodes.filter((node) => node.id !== removeId);
      state.currentGraph.pipeline.nodes.forEach((node) => {
        node.depends_on = (node.depends_on || []).filter((dep) => dep !== removeId);
      });
      delete state.currentGraph.meta.layout[removeId];
      state.selectedNodeId = state.currentGraph.pipeline.nodes[0]?.id || null;
      renderGraphPage(graphId);
    });
  }
  app.querySelectorAll("[data-remove-edge]").forEach((button) => button.addEventListener("click", () => {
    const [source, target] = button.dataset.removeEdge.split("|");
    const node = state.currentGraph.pipeline.nodes.find((item) => item.id === target);
    if (node) {
      node.depends_on = node.depends_on.filter((dep) => dep !== source);
    }
    renderGraphPage(graphId);
  }));
}

function escapeHtml(text) {
  return String(text)
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;");
}

function escapeAttr(text) {
  return escapeHtml(text).replaceAll('"', "&quot;");
}

function parseMaybeJson(text) {
  const trimmed = String(text).trim();
  if (!trimmed || trimmed === "null") {
    return null;
  }
  return JSON.parse(trimmed);
}

async function render() {
  const path = location.pathname;
  try {
    if (path === "/" || path === "/runs") {
      await renderRunsPage();
      return;
    }
    const runMatch = path.match(/^\/runs\/([^/]+)$/);
    if (runMatch) {
      await renderRunPage(runMatch[1]);
      return;
    }
    const graphMatch = path.match(/^\/graphs\/([^/]+)\/edit$/);
    if (graphMatch) {
      await renderGraphPage(graphMatch[1]);
      return;
    }
    navigate("/runs");
  } catch (error) {
    shell(`<div class="panel"><h2>Error</h2><pre>${escapeHtml(error.message || String(error))}</pre></div>`);
  }
}

render();
