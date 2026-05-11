# AgentFlow Web Frontend Revamp Plan

## 1. Background

Current frontend problems are not limited to visual polish. The main issues are structural:

- The information architecture is weak. Pages expose raw objects instead of guiding users through operational tasks.
- Core workflows require too many context switches. Common tasks like finding failures, checking logs, rerunning a node, or editing a graph take too many clicks and too much interpretation.
- The graph editor exposes internal data structures too directly. JSON is treated as a primary editing surface instead of an advanced escape hatch.
- Visual hierarchy is flat. Almost every area uses the same card, spacing, and button treatment, so users cannot quickly distinguish primary actions from supporting context.
- Feedback is underpowered. Save, run, validate, rerun, import, and export actions do not provide strong progress, success, or failure affordances.

This plan focuses on a frontend redesign that improves usability first, then interaction quality, then visual quality. Backward compatibility is not a goal. The latest design should be applied directly.

## 2. Primary Goals

### Product goals

- Make runtime inspection fast: users should reach failed nodes, logs, and rerun actions in one clear path.
- Make graph editing resilient: users should be able to build and edit pipelines without touching raw JSON for common cases.
- Make the UI feel like an operational control plane rather than a demo.

### UX goals

- Reduce click depth for common workflows.
- Reduce the amount of runtime/domain knowledge required to operate the UI.
- Improve state visibility so users always understand what changed, what is running, and what actions are currently available.

### Engineering goals

- Establish a clearer component and layout system.
- Introduce explicit view models where the UI currently renders raw backend shapes directly.
- Reduce fragile interactions caused by `window.prompt`, `window.alert`, and direct `JSON.parse` editor flows.

## 3. Scope

### In scope

- App shell and navigation
- Runs list page
- Run detail page
- Graph editor page
- Shared visual system and interaction primitives
- Frontend state and API interaction improvements required to support the redesign

### Out of scope

- Backend graph/runtime semantics redesign
- New orchestration capabilities unrelated to UI workflows
- Authentication, permissions, or multi-user concerns

## 4. Current Problems By Area

### 4.1 App shell

Problems:

- Top navigation is too thin and provides little workspace context.
- There is no strong page identity, no contextual actions, and no breadcrumb-like orientation.
- The shell does not distinguish between browse mode and edit mode.

Impact:

- The product feels visually unfinished.
- Users do not build a stable mental model of where they are.

### 4.2 Runs page

Problems:

- The page is a flat list plus a small summary strip.
- There is no filtering, searching, sorting, grouping, or failure-first organization.
- Graphs and runs compete on the same page instead of supporting one dominant workflow.
- The page does not proactively help users answer: what failed, what is still running, what changed recently.

Impact:

- The page is weak as a control plane landing page.
- It is hard to scan and triage.

### 4.3 Run detail page

Problems:

- The page forces users to understand internal graph views before they can inspect a problem.
- Logs are buried behind mode switching and selection dependencies.
- Events, artifacts, overview, and logs are organized as peer tabs instead of a task-oriented inspection flow.
- Action buttons are always visible without sufficient context gating or explanation.
- Event rows are raw and noisy, which makes debugging harder instead of easier.

Impact:

- The most important operational page is cognitively expensive.
- Failure triage is slower than necessary.

### 4.4 Graph editor page

Problems:

- The page combines canvas editing, JSON editing, import/export, validation, and runtime actions in one dense surface.
- The right panel is not a proper inspector; it is closer to a generic property dump.
- JSON mode is treated as a first-class mode instead of an advanced fallback.
- Selected node editing is fragile due to direct JSON parsing.
- Import/export interactions use browser primitives instead of integrated UI.
- There is no guided node creation flow, no action grouping, and no keyboard-oriented editing model.

Impact:

- The most complex page is also the least structured.
- Users are pushed toward low-level editing even for common tasks.

### 4.5 Shared visual and interaction system

Problems:

- Buttons, cards, tabs, and panels do not express enough hierarchy.
- Fixed-height containers compress content unnaturally.
- Status presentation is too text-heavy.
- Empty, loading, success, and error states are too generic.
- There is no shared notification pattern for async actions.

Impact:

- The interface feels visually flat and operationally uncertain.

## 5. Target UX Direction

The target product shape should be a focused operations console with a strong editor, not a generic CRUD dashboard.

Design direction:

- Clear hierarchy: one dominant action zone per page.
- Faster triage: the interface should surface failures and active work immediately.
- Safe editing: structured forms first, raw JSON second.
- Dense but readable: operational UIs need high information density without collapsing into noise.
- Intentional motion and transitions: small but meaningful transitions for page changes, panel expansion, and state changes.

Visual direction:

- Preserve the warm control-plane direction only if it is sharpened into a deliberate system.
- Replace generic rounded demo-card styling with clearer surfaces and stronger contrast.
- Use typography and spacing to distinguish overview, inspection, and editing modes.

## 6. Proposed Information Architecture

### 6.1 Global structure

Proposed top-level navigation:

- `Runs`
- `Graphs`
- `New Graph`

Proposed shell additions:

- Persistent page title area
- Contextual secondary actions per page
- Breadcrumb or context line for nested views
- Global async feedback region for toasts and action status

### 6.2 Runs landing page

Proposed page sections:

- Hero summary row:
  Total runs, running, failed in last 24h, last completed
- Filters bar:
  Search, status filter, graph filter, sort selector, refresh toggle
- Main list:
  Failure-first grouped run cards or table rows
- Secondary sidebar:
  Recent graphs, quick create graph, recently failing nodes

Preferred interaction model:

- Default sort by most recent activity
- Quick filters for `Running`, `Failed`, `Needs Attention`
- Inline row actions where safe

### 6.3 Run detail page

Proposed page structure:

- Header:
  Run identity, status, timing, pipeline name, primary actions
- Summary strip:
  Total nodes, completed, failed, running, retries, fanout groups
- Main content split:
  Left = runtime graph or node list
  Right = inspector panel
- Lower panel or tab rail:
  Logs, events, artifacts, output

Preferred inspection flow:

- Default to the first failed node, or first running node if no failures
- Node selection should immediately update inspector and logs
- Stage view and instance view should be toggles inside the graph area, not the primary page structure
- Events should be filterable by type and node

### 6.4 Graph editor page

Proposed page structure:

- Header:
  Graph name, dirty state, save status, primary actions
- Main split:
  Left = graph canvas
  Right = structured inspector
- Bottom utility region:
  Validation results, generated code preview, advanced JSON, import/export tools

Preferred editing flow:

- Select node -> edit structured fields in inspector
- Add node through a guided insert action
- Manage dependencies visually and through a compact dependency editor
- Keep advanced JSON behind a collapsible advanced section

## 7. Implementation Phases

## Phase 1: Foundation and shell

Objective:

- Establish a reusable layout and interaction base before page-specific redesign.

Tasks:

- Rework `AppShell` into a real product shell with page heading support and clearer nav.
- Introduce shared primitives:
  `PageHeader`, `Toolbar`, `FilterBar`, `Panel`, `EmptyState`, `Toast`, `MetricCard`, `SectionHeader`.
- Introduce a notification system for async mutations.
- Normalize button variants and status presentation.
- Refactor CSS tokens into a stronger semantic system:
  surface, border, text, accent, danger, success, warning, focus, muted, code, graph.
- Replace fixed visual patterns that currently force every section into the same card look.

Deliverables:

- New shell layout
- Shared component primitives
- Shared toast/feedback mechanism
- Revised token and base style system

Acceptance criteria:

- All pages render inside a consistent shell.
- Mutations can show pending, success, and error feedback without ad hoc code.
- Base components support mobile and desktop layouts cleanly.

## Phase 2: Runs page redesign

Objective:

- Turn the runs page into a useful control-plane landing page.

Tasks:

- Separate runs and graphs into clearer sections with one dominant focus on runs.
- Add client-side or server-backed search/filter/sort controls.
- Add explicit refresh and optional auto-refresh.
- Add grouped views:
  recent failures, active runs, all runs.
- Improve row/card density:
  status, graph name, started/finished time, failure count, node count, quick actions.
- Add empty-state actions:
  create graph, import graph, open latest graph.

Deliverables:

- Redesigned runs landing page
- Filter and search controls
- Better summary metrics

Acceptance criteria:

- Users can find failed runs without scanning the whole list.
- Users can filter to running or failed runs in one interaction.
- The page remains usable with dozens of runs.

## Phase 3: Run detail redesign

Objective:

- Make runtime triage fast and obvious.

Tasks:

- Restructure page around node-centric inspection.
- Add a smart default selection strategy:
  failed node first, else running node, else first node.
- Split content into:
  graph/list explorer, node inspector, diagnostic output.
- Make logs first-class:
  if a selected node has stdout/stderr, surface them immediately.
- Add event filters and compact event rendering.
- Improve action visibility:
  cancel only when running, resume only when resumable, rerun with clear scope.
- Add status metrics and timing summaries.
- Improve fanout handling:
  stage summary plus quick drill-down to instances.

Deliverables:

- Redesigned run detail page
- Node inspector
- Log viewer and event viewer improvements

Acceptance criteria:

- A user can reach failed-node logs from page load in at most one click.
- Stage vs instance distinction is understandable without reading implementation details.
- Run actions are context-aware and visually safe.

## Phase 4: Graph editor interaction redesign

Objective:

- Make the graph editor usable as the primary authoring surface.

Tasks:

- Replace the current right panel with a structured inspector.
- Organize node editing into sections:
  Basic, Prompt, Dependencies, Execution, Advanced.
- Add explicit graph-level settings separate from node settings.
- Convert import/export flows from browser prompt/alert to modal or sheet flows.
- Move advanced JSON into a dedicated advanced area.
- Add form validation and inline parse errors.
- Add keyboard shortcuts:
  save, add node, delete node, fit view.
- Add guided node creation with sensible defaults.
- Improve dependency editing:
  visual connect plus list editor for precise control.
- Add a non-destructive validation panel with actionable errors.

Deliverables:

- Redesigned graph editor layout
- Structured node inspector
- Safer advanced editing path

Acceptance criteria:

- Common graph edits do not require raw JSON.
- Editing malformed JSON does not corrupt page state.
- Import/export and validation flows feel integrated.

## Phase 5: Visual refinement and polish

Objective:

- Make the product visually coherent and intentionally designed.

Tasks:

- Tune typography scale and spacing rhythm.
- Differentiate overview surfaces, edit surfaces, and diagnostic surfaces.
- Improve graph node styling and edge readability.
- Add subtle transitions for panel changes, selection, and loading.
- Improve empty/loading/error states with stronger affordances.
- Revisit responsive behavior for editor and run detail layouts.

Deliverables:

- Final visual pass
- Motion pass
- Responsive pass

Acceptance criteria:

- Pages feel related but purpose-built.
- Important actions and states are visually obvious.
- The UI no longer reads as a generic internal demo.

## 8. Technical Refactor Plan

### 8.1 Component extraction

Introduce shared components under `server/web/src/components`:

- `layout/PageHeader.tsx`
- `layout/PageSection.tsx`
- `layout/SplitPane.tsx`
- `feedback/ToastRegion.tsx`
- `feedback/InlineNotice.tsx`
- `controls/FilterBar.tsx`
- `controls/SearchInput.tsx`
- `controls/SegmentedControl.tsx`
- `controls/ActionMenu.tsx`
- `status/StatusIcon.tsx`
- `status/StatusSummary.tsx`

### 8.2 State and view-model cleanup

Refactor page state to reduce direct coupling to backend payload shapes.

Recommended additions:

- Run summary selectors for grouped/filtered run views
- Run detail selectors for:
  default selected node, visible events, visible logs, fanout grouping
- Graph editor view models for:
  inspector sections, validation issues, advanced edit state

### 8.3 API and query improvements

Recommended changes:

- Add explicit refresh/invalidate patterns across run-related pages
- Standardize query keys and mutation side effects
- Add optimistic or transitional UI where safe
- Add API error normalization so user-visible failures are understandable

### 8.4 CSS system cleanup

Replace broad page-level class sprawl with:

- semantic tokens
- reusable layout utilities
- component-scoped class naming

If the team wants to keep plain CSS, keep it but impose stronger structure. No need to add a new styling framework unless there is a concrete benefit.

## 9. File-Level Change Map

Likely files to change:

- `server/web/src/components/layout/AppShell.tsx`
- `server/web/src/pages/runs/RunsPage.tsx`
- `server/web/src/pages/run-detail/RunDetailPage.tsx`
- `server/web/src/pages/graph-editor/GraphEditorPage.tsx`
- `server/web/src/components/graph/AgentNode.tsx`
- `server/web/src/components/status/StatusBadge.tsx`
- `server/web/src/styles/tokens.css`
- `server/web/src/styles/globals.css`
- `server/web/src/app/providers.tsx`
- `server/web/src/features/runs/api.ts`
- `server/web/src/features/graphs/api.ts`
- `server/web/src/features/graph-editor/store.ts`

Likely new files:

- shared shell/header/toolbar/filter components
- toast and async feedback components
- run inspector subcomponents
- graph inspector subcomponents

## 10. Risks

- The graph editor may accumulate too many features in one pass if layout and interaction changes are mixed with deep semantic editing changes.
- If advanced JSON editing remains tightly coupled to live store state, structured editing improvements will still feel fragile.
- If the redesign is done page-by-page without shared primitives first, visual inconsistency will persist.

## 11. Execution Order Recommendation

Recommended implementation order:

1. Foundation and shared primitives
2. Runs page redesign
3. Run detail redesign
4. Graph editor redesign
5. Visual polish and responsive refinement

Rationale:

- Shared primitives reduce rework.
- Runs and run detail deliver the highest operational value first.
- Graph editor benefits from design lessons learned during the inspection-side redesign.

## 12. Definition of Done

This frontend revamp is complete when:

- The shell, runs page, run detail page, and graph editor all follow one coherent system.
- Common runtime tasks are discoverable and low-friction.
- Common graph authoring tasks are form-first, not JSON-first.
- Async actions provide strong user feedback.
- The visual system communicates hierarchy, status, and intent clearly.
- The resulting UI feels operationally credible for daily use.
