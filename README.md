# 🌳 GrowthMap — 專案思維生長系統

點一下，讓專案自己長下一步。

## Current MVP

GrowthMap is currently a **tree-first MVP** for growing project ideas as nested nodes. The shipped product supports:

- **Project CRUD** with an auto-created root node
- **Node CRUD** with `child_of` edges
- **Tree view + node detail editing** in the frontend
- **Content blocks** on nodes
- **AI expand / deepen suggestions** through one OpenAI-compatible provider configured by environment variables
- **History** for node actions
- **Markdown export** for the current project tree

Nodes have maturity levels (🌱 seed → 🪨 rough → 🔧 developing → ✅ stable → 🏆 finalized) that auto-advance as content accumulates.

## Not Yet Implemented

The repository also contains blueprint/spec work for a broader system, but the following are **not shipped in the current MVP**:

- mainline / branch governance mechanics
- provider management UI or provider CRUD routes
- agent session workflows and handoff tools
- chat-driven node creation
- multi-relation graph editing in the frontend

## Tech Stack

- **Frontend**: Next.js 15 + React Flow + Zustand
- **Backend**: FastAPI + SQLAlchemy + aiosqlite
- **Database**: SQLite by default (`sqlite+aiosqlite:///./growthmap.db`)
- **AI**: one OpenAI-compatible endpoint configured with `LLM_BASE_URL`, `LLM_API_KEY`, and `LLM_MODEL`

## Quick Start

```bash
# 1. Install backend deps
cd src/backend
python3 -m venv venv && source venv/bin/activate
pip install -r requirements.txt

# 2. Install & build frontend
cd ../frontend
npm install && npm run build

# 3. Set your LLM endpoint
export LLM_BASE_URL="https://api.openai.com/v1"
export LLM_API_KEY="sk-..."
export LLM_MODEL="gpt-4o-mini"

# 4. Run
cd ../..
./start.sh
# → http://localhost:8100
```

## Shipped API Surface

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/api/projects` | GET/POST | List or create projects |
| `/api/projects/{id}` | GET/PATCH/DELETE | Project CRUD |
| `/api/projects/{id}/nodes` | GET/POST | List nodes in a project or create a node |
| `/api/projects/{id}/export` | GET | Export the current project tree as Markdown |
| `/api/nodes/{id}` | GET/PATCH/DELETE | Node CRUD |
| `/api/nodes/{id}/children` | GET | List direct `child_of` children |
| `/api/nodes/{id}/subtree` | GET | Get the nested tree rooted at a node |
| `/api/nodes/{id}/blocks` | GET/POST | List or create content blocks |
| `/api/blocks/{id}` | PATCH/DELETE | Update or delete a content block |
| `/api/edges` | POST | Create an edge |
| `/api/edges/{id}` | DELETE | Delete an edge |
| `/api/nodes/{id}/history` | GET | Read node action history |
| `/api/ai/expand` | POST | Generate child-node suggestions |
| `/api/ai/deepen` | POST | Generate summary/content-block suggestions |

## License

MIT
