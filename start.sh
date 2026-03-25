#!/bin/bash
# GrowthMap 啟動腳本
# Usage: ./start.sh [--rebuild]

DIR="$(cd "$(dirname "$0")" && pwd)"
BACKEND="$DIR/src/backend"
FRONTEND="$DIR/src/frontend"

# Rebuild frontend if requested or not built
if [ "$1" = "--rebuild" ] || [ ! -d "$FRONTEND/out" ]; then
  echo "🔨 Building frontend..."
  cd "$FRONTEND" && npm run build
  echo "✅ Frontend built"
fi

cd "$BACKEND"
source venv/bin/activate 2>/dev/null || python3 -m venv venv && source venv/bin/activate && pip install -q -r requirements.txt

export LLM_BASE_URL="${LLM_BASE_URL:-https://api.openai.com/v1}"
export LLM_API_KEY="${LLM_API_KEY:-your-api-key}"
export LLM_MODEL="${LLM_MODEL:-gpt-5-codex-mini}"
export DATABASE_URL="${DATABASE_URL:-sqlite+aiosqlite:///$BACKEND/growthmap.db}"

echo "🌳 Starting GrowthMap on :8100"
echo "🗄️ DATABASE_URL=$DATABASE_URL"
exec uvicorn main:app --host 0.0.0.0 --port 8100
