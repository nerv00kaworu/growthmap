# GrowthMap HUMAN Growth Map Whitepaper

> **Audience:** GrowthMap users, project owners, and people who review Agent work
> **Purpose:** A guide to the human GUI, data management, AI, and collaboration
> **Version boundary:** This document reflects the current GrowthMap code and existing feature contracts. Minor wording or layout differences may exist in packaged desktop builds; the running interface is authoritative.

---

## 1. What GrowthMap Is

GrowthMap is a project-planning tool built around a growing knowledge graph. It does more than draw categories: it preserves formal node fields, content blocks, a mainline, parallel scenarios, non-tree relationships, operation history, and evidence from collaboration between people and external AI Agents.

It is suitable for software and product development, business plans, research and writing, personal growth, long-term goals, comparing alternatives, and structured human–AI collaboration. Every idea, task, decision, question, and risk can have an explicit place, context, and state.

### 1.1 Six core concepts

1. **Project**: the top-level data container; each project has its own root node, graph, scenarios, relationships, and history.
2. **Node**: the basic work unit. A node should normally express one task, decision, question, risk, or topic. Types include `idea`, `concept`, `task`, `question`, `decision`, `risk`, `resource`, `note`, and `module`.
3. **Parent-child tree and Mainline**: parent-child links express decomposition. A parent can have several children, with one marked as the mainline—the preferred reading and execution path. Other directions remain intact.
4. **Content Block**: repeatable, sortable cards for notes, specifications, decisions, todos, and risks. These are stored separately from formal fields such as Summary, Description, and Rules; GrowthMap does not silently move or rewrite content between them.
5. **Scenario**: a parallel alternative opened from an existing node, allowing exploration without directly changing the mainline. It can later be compared and merged, or archived.
6. **Relation**: an influence outside tree membership, such as `depends_on`, `supports`, `contradicts`, `references`, `blocks`, or `relates_to`.

---

## 2. Getting Started

### 2.1 Choose the interface language

Use the language menu in the top bar to select “Traditional Chinese,” “Simplified Chinese,” or “English.” This changes interface text only; it does not translate project content.

### 2.2 Check the license state

The top bar shows the current state:

- **Paid / Enabled**: editing is available according to the License.
- **Free**: shows the number of currently active projects.
- **Read only**: viewing, searching, export, and backup remain available, but data cannot be created or changed.
- **Checking**: the backend has not yet returned its authoritative state, so mutation controls remain disabled.

### 2.3 Create the first project

1. Click **New Project**.
2. Enter **Project Name**.
3. Optionally enter **Project Description**.
4. Click **Create**, or press Enter.

A name cannot contain only whitespace. Prefer a recognizable name such as “GrowthMap Official User Whitepaper” or “2026 Product Launch Plan,” not “New Project” or “Other.”

---

## 3. Main Screen Tour

### 3.1 Top toolbar

From left to right, the main controls are the GrowthMap logo, language selector, project selector, scenario selector, license state, **New Project**, **Settings**, **Search nodes**, the desktop **Database Workspace**, and **Keyboard Shortcuts**.

### 3.2 Central graph

A node card can show its type icon, title, summary, maturity color, child count, and `MAIN` badge. Scenario nodes use a purple dashed appearance.

- Single-click a node: select it and open the right panel.
- Click empty space: clear the selection.
- Double-click a node: enter or leave Focus Mode.
- Canvas controls: zoom, center, or fit the graph.
- MiniMap: navigate large projects quickly.

### 3.3 Focus Mode

Double-clicking a node shows that node, its ancestors, up to three descendant levels, and same-level siblings. This reduces visual noise in large graphs. Click **Exit Focus** or double-click again to leave.

---

## 4. Project Management

### 4.1 Switch, archive, and restore

Choose a target from **Select Project**; archived projects carry an archive icon. Wait for synchronization to finish before switching again or editing.

Use these actions under **Settings**:

- **Archive Project**: retains the data and its read/export access but removes it from the everyday active list.
- **Restore Project**: restores an archived project to `active`.

Archiving is not deletion. It is appropriate for completed, paused, or temporarily inactive work.

### 4.2 Export and import

**Settings** provides:

- **Export Spec**: `{project_name}_spec.md`, oriented toward a structured implementation specification.
- **Export Markdown**: `{project_name}.md`, useful for reading, sharing, or publishing.
- **Export JSON**: `{project_name}.json`, preserving a machine-readable project structure for exchange or project-level backup.

To import JSON, choose **Settings → Import JSON**, select a GrowthMap JSON file, and wait for the success message and refreshed project list. This imports project data. **Import Existing DB** replaces the entire workspace and carries a different risk.

---

## 5. Creating and Managing Nodes

### 5.1 Add a child node

Select the parent, then in the right panel open **Content → Content Tools**, choose a node type, enter a title, and click `+` or press Enter. The node is added to the current path; this is not the same as opening a scenario.

### 5.2 Move, mark mainline, and delete

- **Move**: connecting nodes in Tree Mode reassigns the source node’s parent. The source and all descendants move under the target parent, so verify drag direction first.
- **Set as Mainline**: in the child list under **Scenario Tools**, click **Set as Mainline** on a non-mainline child. This marks priority; it does not delete siblings.
- **Delete**: use the trash icon or Delete/Backspace, then confirm. First check for descendants, external relationships, important content blocks, whether a scenario would preserve the work better, and whether a backup exists.

### 5.3 Right-side panel

It has four tabs:

- **Content**: formal data, content blocks, documents, children, and scenarios.
- **AI**: expand or deepen a node.
- **Chat**: discuss the current node context with AI.
- **History**: operation history and Agent implementation reports.

At the bottom, **Edit** enters formal-field and content-block editing; **Save** stores the node title, summary, and formal fields; **Cancel** leaves the current formal-field edit; the trash icon deletes the node. A content block’s own **Save** is independent of the node-level **Save**.

---

## 6. Complete Node Field Dictionary

### 6.1 Title

The node’s main name on the graph. Express one thing per title. Use a verb for a task, such as “Complete login-flow testing,” and state a decision directly, such as “Use SQLite as the local database.”

### 6.2 Node type

Selected when creating a child. It controls iconography and semantic classification; it does not automatically run a workflow. See Section 1.1 for available types.

### 6.3 Maturity

The degree to which content has progressed from an idea to a settled result:

- `Seed`: newly surfaced, with little information.
- `Rough`: an outline exists, but validation or detail is missing.
- `Developing`: being elaborated or implemented.
- `Stable`: reliable enough for regular use.
- `Finalized`: decided and completed; changes deserve extra care.

Maturity is not a task percentage. `Developing` is not the same as workflow status `in_progress`.

### 6.4 Summary

In one to three sentences, explain what this is, why it matters, and the current conclusion or next step, so readers can understand without opening all details.

### 6.5 Status

Stores the node’s lifecycle state. The current GUI uses free text and defaults to `active`. Teams should agree on stable values such as `active`, `archived`, `blocked`, and `deprecated`, rather than mixing synonyms like `done`, `completed`, and `finish`.

### 6.6 Workflow status

Describes the execution stage. The current GUI uses free text and defaults to `draft`. Recommended values are `draft`, `ready`, `in_progress`, `waiting_review`, and `completed`. Status describes lifecycle; Workflow status describes execution.

### 6.7 Priority

A numeric relative ordering, default `0`. The GUI does not enforce a fixed range. A team might standardize on `0` unsorted, `1` highest, `2` high, `3` normal, and `4` low.

### 6.8 Confidence

How trustworthy the current judgment or content is. Range `0`–`1`, step `0.01`, default `0.5`. For example, `0.20` is mostly a guess, `0.50` has partial evidence, `0.80` is broadly reliable, and `1.00` should be reserved for explicit, verifiable claims.

### 6.9 Description

The full background and purpose, answering “What problem does this node address?”

### 6.10 Rules

Rules and invariants the node must obey, for example, “Every data write must leave operation history.”

### 6.11 Constraints

External, technical, schedule, budget, or permission limits, for example, “Only Windows local disks are supported.”

### 6.12 Examples

Positive examples, counterexamples, input/output samples, or concrete use cases.

### 6.13 Questions / acceptance

Open questions or verifiable acceptance conditions, for example, “Can an existing project be read after installation?”

### 6.14 Decision notes

The final decision, its reasoning, alternatives, and why other directions were not selected.

### 6.15 File paths

One related file location per line. This stores text only; it does not grant GrowthMap or an Agent permission to read or write the file.

---

## 7. Content Blocks and Bound Documents

### 7.1 Content blocks

Supported human-facing types are Note `note`, Spec `spec`, Decision `decision`, Todo `todo`, and Risk `risk`.

To add one, enter node Edit mode, select a type, fill **Block title (optional)** and content, then click **Add Content Block**. At least one of title or content is required. After changes, click that block’s **Save**; use `↑` and `↓` to reorder; click **Delete** to remove it. Deletion explicitly warns that it cannot be recovered, so do not rely only on global undo.

### 7.2 Bound documents

**Bound Documents** stores references; it does not copy document content into GrowthMap.

- **Document Title**: display name.
- **URL / Path**: a web address or path string.
- **Document Summary (optional)**: purpose or content description.

At least one of Title or URL is required. After creation, use **Open**; in Edit mode, use **Remove**. Binding a path does not grant Agent file access and does not guarantee that another device can open the same path.

---

## 8. Complete Scenario Workflow

Use a scenario when an option is unsettled, the mainline must remain protected, architectures or strategies need comparison, or an Agent should explore without writing into the official direction yet. For ordinary expansion, add a child node instead.

1. Select a source node that already has children.
2. Under **Scenario Tools**, click **Open New Scenario**.
3. Enter the required name and optional description.
4. Switch from the scenario menu beside `🌿 main` in the top bar.

The interface displays **Scenario Mode**. To merge, click **Review and Merge**, compare the source mainline and scenario root—including title, summary, maturity, node count, and content-block count—choose **Merge into Mainline Node**, then click **Confirm Merge**. The scenario ends and its complete subtree is attached below the selected mainline node; this is not a field-by-field overwrite of the source.

The mainline cannot be archived. While viewing a scenario, use the dangerous-actions area in Settings to archive it. **Scenario History** shows operations and timestamps.

---

## 9. Search, Heatmap, and Relationship Graph

### 9.1 Search

Enter a node name in the top bar. Matches are marked on the graph and up to ten appear in the dropdown. Click a result to select it, press Enter to jump to the first, or Esc to clear.

### 9.2 Heatmap

Colors represent time since last update: green under 1 day, yellow 1–3 days, orange 3–7 days, red over 7 days, and purple for never updated. The heatmap finds neglected areas; it does not indicate quality or urgency.

### 9.3 Tree Mode and Graph Mode

- **Tree Mode**: connecting nodes reassigns the parent.
- **Graph Mode**: connecting nodes creates only a non-tree relationship and does not change parent-child structure.

Always confirm the mode before dragging a connection. To create a relationship, switch to **Graph Mode**, select a relationship type, connect source to target, then inspect it in the lower-left relationship panel and adjust weight or notes. Direction matters: “Release production version” `depends_on` “Complete Windows acceptance.”

### 9.4 Relationship filter fields

- **Search nodes**: narrow by title.
- **Relationship range**: All, 1 hop, or 2 hops.
- **Direction**: Both, Upstream, or Downstream.
- **Minimum weight**: show only relationships meeting the threshold.
- **Show relationships**: select relationship types.
- **Weight**: `0`–`1`, step `0.05`.
- **Relationship basis / notes**: record why the relationship exists.

---

## 10. AI Features and LLM Providers

### 10.1 Create a Provider first

Open **Settings → LLM Settings**. The AI tab has selectable Providers only after a profile exists. Mock does not call an external API; expansion, deepening, and chat with real models may consume third-party API quota.

### 10.2 Expand, deepen, and chat

- **Expand Branch**: generates several suggested child nodes from the current node. Growth modes are **Focus Mainline**, **Explore Adjacent**, and **Challenge Assumptions**. You can also enter **Instructions for AI**. Review each result with **Adopt** or **Ignore**, or use **Adopt All**; item-by-item review is recommended.
- **Deepen Content**: suggests a richer summary and content blocks. Apply only the summary, accept or ignore blocks individually, or accept all. Suggestions become formal data only after selection.
- **Chat**: uses the current node’s ancestor path as context. Enter a question and press Enter or **Send**. Switching nodes resets visible chat. Answers do not automatically become formal node data; manually curate durable conclusions into fields or blocks.

AI waits for at most about 62 seconds and does not show a fake percentage. If a profile changes during a request, submit again. Preserve the Request ID when an error occurs. After changing the model name, click **Save Model** before the backend can use it.

### 10.3 Provider field dictionary

- **Saved Provider**: select an existing profile or **Create New Provider**; the dot indicates enabled state.
- **Display Name**: required human-readable profile name.
- **Provider**: OpenAI, Anthropic, Google Gemini, OpenClaw, Custom, OpenAI-compatible, or Mock (Demo).
- **Base URL**: API base address. Mock may leave it empty; self-hosted or compatible services require the correct path.
- **API key environment variable name**: semantic credential name, default `GROWTHMAP_LLM_KEY_DEFAULT`.
- **API Key**: required for real models. When editing an existing Provider, leave it empty to retain the current key. The desktop app uses operating-system secure storage and does not place secrets in the screen, localStorage, or SQLite; if secure storage is unavailable, saving is refused.
- **Model**: model name. Leaving it empty may use that Provider’s default.
- **Add New**: clears the form for a new Provider.
- **Save and Use**: stores metadata, securely stores credentials, selects the Provider, then reloads authoritative settings. A partial failure is shown explicitly.
- **Credential Recovery**: after an interrupted update, either enter the credential again and finish, or retry removal.

---

## 11. History, Undo, and Shortcuts

Under **History**, click **View Operation History** to see node creation and editing, project creation, maturity promotion, AI expansion/deepening, actor type, and time. The bottom also shows an abbreviated node ID, creation/update times, and Agent implementation tracking when readback exists. History is audit data, not a complete restore system for arbitrary points in time.

Shortcuts: `Esc` clears selection or closes some overlays; Delete/Backspace deletes the selected node after confirmation; `Ctrl+Z`/`Cmd+Z` undoes an eligible operation; the interface lists `E` for AI expansion and `D` for AI deepening. High-risk operations such as content-block deletion and DB restore must not rely only on undo.

---

## 12. Database Workspace and Backups

On desktop, **DB** in the top bar shows the full current DB path, project count, database size, SHA-256 digest prefix, and most recent backup time.

- **Select Existing Workspace**: switch to another GrowthMap workspace; the application restarts after success.
- **Back Up Now**: create a GrowthMap-managed backup, especially before large changes, imports, merges, or upgrades.
- **Import Existing DB**: first backs up the current data, then replaces the entire workspace with the selected database. It does not append one project.
- **Open Backup Folder**: reveal the managed backup location in the operating system.
- **Restore**: restore a selected backup. GrowthMap first backs up the current state; do not close the app during the operation.

A workspace must be on a Windows local disk. To protect SQLite, WSL filesystems, UNC paths, network drives, and cloud-synchronized folders are unsupported. An Agent running in WSL must use Agent Port/API rather than opening SQLite directly.

Always back up before JSON/DB import, restore, large graph restructuring, scenario merge, long-running Direct collaboration, or an application upgrade, and after important milestones. Keep managed DB backups, JSON exports of important projects, and readable Markdown/Spec exports. GrowthMap does not replace Git, off-site backups, or a formal disaster-recovery system.

---

## 13. Human Management of Agent Collaboration

### 13.1 Distinguish the two Agent features

An **Agent Work Session** is a human tracking and review panel for delegation goals, scope, mode, progress, reviewable artifacts, and closing summaries. It does not launch an external Agent or call an LLM.

**Agent Access / Agent Port** is the connection layer through which an external MCP-compatible Agent can read or make limited changes through a localhost graph API. It does not grant filesystem, Git repository, shell, Provider credential, deployment, or payment access.

### 13.2 Enable Agent Access

In the desktop app, open **Settings → Agent Access / Agent Port**:

1. Choose an access mode.
2. Choose a lifetime.
3. Enable access and wait until the backend confirms `enabled`.
4. Copy or download the universal MCP configuration.
5. Add that MCP server to the external Agent client.
6. Run the connection test.

Only one workspace master grant can be active in a workspace at a time. Switching GrowthMap projects does not require rebuilding access. Use the configuration GrowthMap generates; do not guess executable paths or paste credentials into chat or ordinary configuration files.

### 13.3 Three modes

- **Read only**: the Agent can list and read projects, graphs, and node context, but cannot propose or directly write. Use it for analysis, audits, and search.
- **Review first**: the Agent can read and submit a proposal, but formal data changes only after human approval. Use it for new Agents, high-risk projects, and strict review. This is the recommended general starting point.
- **Direct collaboration**: within the grant, the Agent can directly apply limited, typed, atomic creation or updates of nodes, relationships, content blocks, and scenarios. It does not permit arbitrary rewriting, deletion, DB operations, shell access, or permission changes.

### 13.4 Lifetime, revocation, and rotation

Choices are **For this work session**, **24 hours**, **7 days**, **30 days**, and **Until manually disabled**. A work-session grant still has a finite lifetime; only the manual option persists. Disable access when work finishes. If exposure is suspected, use **Regenerate** for atomic credential rotation.

### 13.5 Review, progress, and readback

In Review first, inspect the proposal’s purpose, target, expected changes, relationship direction, and scope. Approval makes it effective; rejection does not change the formal graph. Direct collaboration should still use short lifetimes and small batches, followed by a review of human-visible history.

An Agent can report started, progress, blocked, completed, or failed events. A readback is evidence of external work and may contain a summary, commits, files, tests, decisions, risks, todos, and evidence. It records outcomes; it does not execute repository work and is not itself a formal graph change.

### 13.6 Agent Work Session panel fields

- **Work Goal**: a testable deliverable, not a vague instruction.
- **Scope**: Node or Scenario Root.
- **Target**: the actual node or scenario root being handled.
- **Work Mode**: **One-off**, **Collaboration**, or **Background Tracking**. These are tracking labels and do not alter the external Agent environment.
- **Provider (optional)**: records the intended Provider; the panel does not call it automatically.
- **Session Status**: **Not Started**, **In Progress**, **Pending Review**, **Completed**, or **Canceled**.
- **Result / Closing Summary**: finished outcome, remaining issues, or cancellation reason.
- **Artifact Proposal**: the GUI can propose a child-node title for approval. Approval writes it; rejection preserves the review result without applying it.

---

## 14. Human–Agent Collaboration Examples

### Scenario A: analysis only

The human prepares the target and enables **Read only**. The Agent reads the project and context, then provides external analysis or a readback. The human decides whether the graph should change.

### Scenario B: proposal and approval

Enable **Review first**. The Agent reads the latest state and submits a reasoned proposal. The human checks each item and approves or rejects it. This is recommended for new Agents or important projects.

### Scenario C: a trusted Agent collaborates directly

Back up first, then enable time-limited **Direct collaboration**. Ask the Agent to work in small batches and report meaningful milestones. Review readback and history afterward, then disable or rotate access.

### Complete example: login-feature test plan

1. The human creates a “Login feature” node and fills Rules, Constraints, and Questions / acceptance with security rules, supported platforms, and acceptance conditions.
2. Create a DB backup and enable Review first for 24 hours.
3. The Agent proposes “Successful login test” and “Expired session test” tasks, a “Brute-force rate-limit” risk, and a test-spec content block.
4. The human reviews and approves.
5. If the Agent implements tests in an external repository, it submits readback with real commits, files, test results, risks, and todos.
6. The human checks evidence under node History, updates maturity and workflow status, and disables Agent Access.

---

## 15. Safety Principles and FAQ

### Safety principles

Humans must review AI suggestions. Never share a token or API key in chat. Bound paths and `file_paths` do not authorize file access. Agent Access is a local graph API only. Even in Direct collaboration, Agent Port does not provide deletion, DB import/restore, destructive merge/archive, license changes, file/repository/shell access, Provider keys, payments, or deployment. Access should fail closed after expiration or revocation.

### FAQ

**Why can’t I edit, or why is New Project disabled?** Check the license state; Read only and Checking disable mutations.
**Why are AI actions disabled?** There may be no enabled Provider, the selected Provider may be missing/disabled, credential setup may be incomplete, the model may not have been saved, or a request may still be running.
**What should I do after an AI error?** Preserve the error code and Request ID, then check Provider, Base URL, model, and API Key.
**Why did chat disappear after switching nodes?** Visible chat resets with node context. Curate durable conclusions into formal data.
**A content-block reorder was saved but reload failed—what now?** Refresh first; do not immediately repeat the move.
**What happens after a scenario merge?** The entire scenario subtree is attached to the selected mainline node; source fields are not overwritten one by one.
**Why can’t the Agent see the project selected in the GUI?** By design, an external Agent must explicitly select a project rather than borrowing GUI selection.
**What does an Agent write conflict mean?** Data changed after the Agent read it. The Agent should reread and rebuild the change, not overwrite newer work.
**Why is there no token in MCP configuration?** Desktop uses local discovery and operating-system secure credential storage.
**Can a WSL Agent open SQLite directly?** No. Use Agent Port/API.

---

## 16. Feature and Version Boundaries

This guide covers current GUI capabilities for projects, node trees and mainlines, focus and search, formal fields, content blocks, document references, scenarios, relationship graphs, heatmaps, AI expansion/deepening/chat, Provider management, three exports and JSON import, desktop DB workspace/backup/restore, human Agent Work Sessions, Agent Access, history, and readback.

The source repository may also contain a thin CLI and MCP source adapter. Do not describe those as command-line tools guaranteed to ship with every desktop installation. The formal desktop path is the packaged `growthmap-mcp.exe` and the universal configuration generated by the application.

GrowthMap does not launch an external Agent, grant file access because a path is referenced, grant shell/repository access through Agent Access, automatically turn AI chat into formal data, guarantee AI correctness, or perform payments or deployments.

---

## 17. Quick Start and Node Template

1. Create a project and first-level nodes; choose a mainline.
2. Fill Summary, Rules, Constraints, and acceptance criteria for important nodes.
3. Use content blocks for specifications and risks.
4. Use scenarios for uncertain directions and relationships for dependencies or blockers.
5. Configure a Provider before using AI, and review each suggestion.
6. Back up before large changes.
7. Start Agent collaboration with Read only or Review first; inspect History/readback and disable access when done.

```text
Title:
Node type:
Maturity: Seed
Summary:

Description:
Rules:
Constraints:
Examples:
Questions / acceptance:
Decision notes:

Status: active
Workflow status: draft
Priority: 0
Confidence: 0.50
File paths:
```

---

## 18. Separate Guide for an External LLM

This whitepaper is the complete guide for human users. To connect an external LLM/Agent to GrowthMap, open the separate **[Agent/LLM Operations Guide](/en/whitepaper/agent)** and supply that guide to the external LLM. It contains the live connection, tool-use, and safety rules the Agent must follow; this human GUI tutorial is not a substitute for it.
