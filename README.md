# 🌳 GrowthMap — 專案思維生長系統

點一下，讓專案自己長下一步。

## What is this?

GrowthMap is a project growth system where nodes represent ideas, decisions, and modules. You can:

- **Expand**: Let AI suggest child nodes for unexplored areas
- **Deepen**: Let AI draft content blocks for empty nodes
- **Grow via chat**: Talk to your AI assistant, who plants nodes from your conversations
- **Export**: Generate a full Markdown document from your project tree

Nodes have maturity levels (🌱 seed → 🪨 rough → 🔧 developing → ✅ stable → 🏆 finalized) that auto-advance as content accumulates.

## Tech Stack

- **Frontend**: Next.js 15 + React Flow + Zustand (static export)
- **Backend**: FastAPI + SQLAlchemy + aiosqlite (SQLite)
- **AI**: Any OpenAI-compatible API (pluggable via env vars)

## Quick Start

```bash
# 1. Install backend deps
cd src/backend
python3 -m venv venv && source venv/bin/activate
pip install -r requirements.txt

# 2. Install & build frontend
cd ../frontend
npm install && npm run build

# 3. Set your LLM provider
export LLM_BASE_URL="https://api.openai.com/v1"
export LLM_API_KEY="sk-..."
export LLM_MODEL="gpt-4o-mini"

# 4. Run
cd ../..
./start.sh
# → http://localhost:8100
```

## API

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/api/projects` | GET/POST | List/create projects |
| `/api/projects/{id}/tree` | GET | Get full node tree |
| `/api/projects/{id}/export` | GET | Export as Markdown |
| `/api/nodes/{id}` | GET/PATCH/DELETE | Node CRUD |
| `/api/nodes/{id}/blocks` | GET/POST | Content blocks |
| `/api/nodes/{id}/history` | GET | Operation history |
| `/api/ai/expand` | POST | AI branch suggestions |
| `/api/ai/deepen` | POST | AI content enrichment |

## License

MIT
