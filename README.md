# 🌳 GrowthMap

AI-powered project growth system — build ideas as trees, let AI expand branches and deepen content, then accept or reject suggestions.

## Product boundary (2026-07-18)

GrowthMap is the canonical **authoring/editor** system. It manages editable project trees, authoring exports, and opt-in editor AI workflows. Its local canonical DB/snapshots are operator-managed data, not part of the release archive. Player Web/API runtime, gameplay release provenance, and replay tooling now live exclusively in the independent `abyss-bureau` repository; GrowthMap mounts no `/api/player` routes and runs no player runtime migrations.

## Security remediation release (`v0.1.0-authoring.2`)

This release is the security-only successor to immutable tag `growthmap-authoring-v0.1.0-authoring.1`; the old tag is never moved or overwritten. Browser code stores only provider profile ID/type/model metadata. API keys are accepted only by the localhost backend secret endpoint, written atomically to the configured env file with mode `0600`, and never returned. Provider secret names must match `GROWTHMAP_LLM_KEY_[A-Z0-9_]{1,96}`. AI expand/deepen/chat/test requests carry `provider_id` only; endpoint and credentials are resolved server-side.

The release launcher and backend are localhost-only: non-loopback frontend/backend binds other than `127.0.0.1` or `localhost` fail closed, and Trusted Host validation rejects non-local Host headers. Public deployment is unsupported until an authenticated desktop-ready boundary exists.

## ✨ Features

- **Tree-based project canvas** — visual mind-map with React Flow
- **AI Expand** — generate child node suggestions from any node
- **AI Deepen** — enrich node summaries and add content blocks
- **Undo** — up to 10 levels of undo for all tree mutations
- **Node Search** — search nodes by title with highlight + jump
- **Import / Export** — JSON full project backup, Markdown export
- **Drag-to-reparent** — drag edges in the canvas to move nodes
- **Keyboard Shortcuts** — Esc, E, D, Delete, Ctrl+Z
- **Auto-maturity** — nodes auto-advance maturity as content grows
- **Node Types** — idea, concept, task, question, decision, risk, resource, note, module
- **Mainline tracking** — mark primary child paths for structured work
- **Parallel branches** — create, switch, merge, and archive proposal branches
- **Provider-neutral Agent Port v1** — scoped grants, revision-safe proposals/direct batches, context packets, progress and implementation readback over REST/CLI/MCP
- **DB auto-backup** — local SQLite backup before destructive operations
- **Dark theme** throughout

## 🚀 Quick Start

### Prerequisites
- Python 3.10+
- Node.js 18+

### Build and run (authoring editor)

```bash
# Backend dependencies
cd src/backend
python3 -m venv venv
venv/bin/pip install -r requirements.lock

# Frontend production build
cd ../frontend
npm ci
npm run build

# Return to repository root and start already-built services
cd ../..
./scripts/start_growthmap.sh
```

Open <http://127.0.0.1:3100>. Before launching, set an explicit `DATABASE_URL` pointing to the intended authoring SQLite/DB location; the launcher refuses to choose or create a default data file. It binds only to loopback by default, never installs dependencies, never kills an existing listener, and never runs a content import command. Backend startup may apply its documented lightweight schema compatibility steps to that explicit database. Set explicit `GROWTHMAP_*` variables only when a different host or port is intended.

`./start.sh` remains a compatibility wrapper for the same launcher. For local development, run the backend and `npm run dev` separately; development mode is not the release launch path.

## ⚙️ LLM Configuration

Click **⚙️ LLM 設定** in the header to configure:

| Provider | Notes |
|----------|-------|
| OpenAI | `gpt-4o`, `gpt-4-turbo`, etc. |
| OpenAI-compatible | Any base URL (LM Studio, Ollama, etc.) |
| Anthropic | Via OpenAI-compat proxy |

Settings are stored in `localStorage`.

## ⌨️ Keyboard Shortcuts

| Key | Action |
|-----|--------|
| `Esc` | Deselect / close panels |
| `E` | AI Expand selected node |
| `D` | AI Deepen selected node |
| `Delete` | Delete selected node |
| `Ctrl+Z` | Undo |

Click ⌨️ in the header to view shortcuts overlay.

## 📦 Release boundary

This repository packages **only the GrowthMap authoring/editor**: the project canvas, canonical authoring data, reviewable exports, and opt-in editor AI integrations. It does **not** package the Abyss Bureau player Web/API runtime, its player database, gameplay release/replay machinery, payment, PvP, runtime LLM calls, or runtime image generation. Those player-runtime concerns belong to the independent `abyss-bureau` repository.

Historical player-runtime reports or candidate artwork may exist in local archives, but are excluded by `.gitignore` and are not release inputs for this authoring package.

## 🏗️ Architecture

```
growthmap/
├── start.sh                  # One-click launcher
├── .github/workflows/ci.yml  # Frontend + backend quality gates
├── src/
│   ├── backend/              # FastAPI + SQLAlchemy + SQLite
│   │   ├── main.py
│   │   ├── api/routes.py     # REST API
│   │   ├── ai/routes.py      # AI expand/deepen
│   │   ├── models/           # DB models + schemas
│   │   └── db/               # Async SQLite
│   └── frontend/             # Next.js 15 + React Flow + Zustand
│       └── src/
│           ├── app/page.tsx  # Main layout + header
│           ├── stores/       # Zustand store
│           ├── components/   # MindMap, NodePanel, GrowthNode, ...
│           └── lib/          # API client, types, LLM config
```

```
Browser ──► Next.js (3100) ──► FastAPI (8100) ──► SQLite
Agent CLI/MCP ───────────────► /agent/v1 REST (localhost, scoped bearer grant)
                                      └──► LLM API (OpenAI/compat)
```

Agent Port protocol and product invariants are normative in [`docs/PRODUCT-CORE-v1.md`](docs/PRODUCT-CORE-v1.md) and [`docs/AGENT-PORT-v1.md`](docs/AGENT-PORT-v1.md). GrowthMap does not execute external agents or bind the port to a provider/model. The desktop sidecar includes the Agent Port REST implementation and schema support; the optional repository-level `scripts/growthmap_agent.py` and `scripts/growthmap_mcp.py` clients are source-distribution tools and are not promised as entries inside the packaged desktop ASAR.

## ✅ Quality Gates

The repository runs these authoring-editor checks locally and in GitHub Actions:

```bash
git diff --check

cd src/frontend
npm ci
npm run lint
npm run typecheck
npm run build

cd ../backend
python -m compileall -q -x 'venv|__pycache__' .
DATABASE_URL='sqlite+aiosqlite:///:memory:' python -m unittest discover -s tests -v
```

The backend smoke test uses an in-memory SQLite database and does not call an LLM provider. Use `requirements.lock` for release builds; `requirements.txt` remains the editable dependency policy. Release packaging additionally requires the checklist in `docs/RELEASE-CONVERGENCE-CHECKLIST-v1.md` to be fully satisfied.

## 📸 Screenshots

_(Coming soon)_

## 🤝 Contributing

1. Fork the repo
2. Create a feature branch: `git checkout -b feat/my-feature`
3. Commit: `git commit -m "feat: ..."`
4. Push and open a PR

Please keep all user-facing text in Traditional Chinese (繁體中文), and maintain dark theme throughout.

## 📄 License

MIT

### License issuance Phase 1

Payment-independent device activation and desktop unlock are specified in [`docs/LICENSE-ISSUANCE-v1.md`](docs/LICENSE-ISSUANCE-v1.md). This source module is not a deployed issuance service: production HSM/KMS, API authentication/TLS, rollback-resistant storage, recovery controls, and Windows signed-package validation remain release gates.
