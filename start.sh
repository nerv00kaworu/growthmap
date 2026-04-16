#!/bin/bash
# Start GrowthMap (backend + frontend)
cd "$(dirname "$0")"

# Start backend
cd src/backend
source venv/bin/activate 2>/dev/null || (python3 -m venv venv && source venv/bin/activate && pip install -r requirements.txt)
uvicorn main:app --host 0.0.0.0 --port 8100 &
BACKEND_PID=$!
cd ../..

# Start frontend
cd src/frontend
npm install --silent 2>/dev/null
npx next dev -p 3100 &
FRONTEND_PID=$!
cd ../..

echo "🌳 GrowthMap running: http://localhost:3100"
echo "   Backend: http://localhost:8100"
echo "   Press Ctrl+C to stop"

trap "kill $BACKEND_PID $FRONTEND_PID 2>/dev/null" EXIT
wait
