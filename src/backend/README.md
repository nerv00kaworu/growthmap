# GrowthMap Backend

Current status: this backend is the **authoring/editor implementation** of GrowthMap. It supports the tree-first workflow described below. Player Web/API runtime and gameplay execution were split to the independent `abyss-bureau` repository and are not part of this package.

## Setup

```bash
cd growthmap/src/backend
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.lock
DATABASE_URL='sqlite+aiosqlite:////absolute/path/to/growthmap.db' \
  uvicorn main:app --host 127.0.0.1 --port 8100
```

Set an explicit `DATABASE_URL` for every release/production-like run; do not let a launcher silently choose a local DB path. On startup the service applies its documented lightweight schema compatibility steps to that explicit database, so take an operator-managed backup before upgrading an existing database. For local LLM configuration, copy the repository `.env.example` and set `LLM_BASE_URL`, `GROWTHMAP_LLM_KEY_DEFAULT`, and `LLM_MODEL`. Do not commit a real API key.

## Stack

- FastAPI
- SQLAlchemy + aiosqlite
- SQLite
- Pydantic v2

## Shipped Capabilities

- project CRUD with automatic root-node creation
- node CRUD plus `child_of` edge creation from parent assignment
- subtree, Markdown, JSON, and spec export endpoints
- content block CRUD and node history via action logs
- mainline selection for child edges and mainline-path queries
- proposal branch creation, switching data, comparison, merge, ranking, and archive endpoints
- AI expand / deepen / chat, with mock and OpenAI-compatible providers supplied per request
- server-stored provider profiles that reference local environment-variable names; API keys are never stored in SQLite or returned to the frontend

## Current Boundaries

- This package is authoring-only: it does not mount `/api/player`, import player gameplay packs, or run player-runtime migrations.
- The frontend is **tree-first**. It exposes the proposal-branch workflow, but it does not provide a general visual editor for every edge relation type.
- Provider profiles persist only provider metadata, endpoint, model, and the name of the environment variable holding its API key. Configure that secret in the local `.env`; it is never stored in SQLite or returned over the API.
- `AgentSession` remains groundwork; task/session orchestration is not implemented yet.
- AI calls are opt-in and depend on a configured provider; automated tests never use external model credentials.
- SQLite is the tested local database. PostgreSQL deployment and migration coverage are not part of this MVP.

`requirements.lock` is the reviewed release lock for Python 3.12; update it deliberately after changing `requirements.txt`.

## Quality Checks

```bash
# From src/backend
python -m compileall -q -x 'venv|__pycache__' .
DATABASE_URL='sqlite+aiosqlite:///:memory:' python -m unittest discover -s tests -v
```

The smoke test forces an in-memory SQLite URL before importing the app, so it cannot touch the local `growthmap.db`.

## Authoring.2 security boundary

Provider profiles keep non-secret endpoint/model metadata in SQLite. Writable secret names are restricted to `GROWTHMAP_LLM_KEY_[A-Z0-9_]{1,96}`; arbitrary process variables are rejected on create, patch, and write. Configure a key through `PUT /api/providers/{provider_id}/secret` from localhost only; it atomically updates `GROWTHMAP_ENV_FILE` (default repository `.env`) with mode `0600`, returns an empty `204`, and provider/list responses never include the value. All AI requests and connection tests accept `provider_id` only; per-request `api_key` and `base_url` overrides are rejected.

The maintained release launcher refuses any any `GROWTHMAP_BACK_HOST` or `GROWTHMAP_FRONT_HOST` other than `127.0.0.1` or `localhost` (including IPv6 loopback). `TrustedHostMiddleware` independently admits localhost/test hosts so CORS is not the only network boundary. Public binding is intentionally unsupported in this candidate.
