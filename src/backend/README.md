# GrowthMap Backend

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
