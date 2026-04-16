# 🌳 GrowthMap

AI-powered project growth system — build ideas as trees, let AI expand branches and deepen content, then accept or reject suggestions.

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
- **Mainline tracking** — mark primary branch for structured paths
- **DB auto-backup** — DB backed up before any destructive operation
- **Dark theme** throughout

## 🚀 Quick Start

### Prerequisites
- Python 3.10+
- Node.js 18+

### One-click Start

```bash
./start.sh
```

Open [http://localhost:3100](http://localhost:3100)

### Manual Setup

**Backend:**
```bash
cd src/backend
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
uvicorn main:app --host 0.0.0.0 --port 8100
```

**Frontend:**
```bash
cd src/frontend
npm install
npx next dev -p 3100
```

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

## 🏗️ Architecture

```
growthmap/
├── start.sh                  # One-click launcher
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
                                      └──► LLM API (OpenAI/compat)
```

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
