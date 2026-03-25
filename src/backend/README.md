# GrowthMap Backend

Current status: this backend is the **MVP implementation**, not the full blueprint/spec surface.

## Setup
```bash
cd growthmap/src/backend
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
uvicorn main:app --reload --port 8100
```

## Stack
- FastAPI
- SQLAlchemy + aiosqlite
- SQLite
- Pydantic v2

## Shipped Capabilities

- project CRUD with root-node creation
- node CRUD plus `child_of` edge creation from parent assignment
- subtree and Markdown export endpoints
- content block CRUD
- node history via action logs
- AI expand / deepen suggestion endpoints backed by one OpenAI-compatible provider from env vars

## Not Shipped Yet

- provider configuration routes/UI
- agent session routes/UI
- generalized graph editing for non-`child_of` relations
- mainline / branch health mechanics
