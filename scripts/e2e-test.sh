#!/usr/bin/env bash
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
BACKEND_DIR="$REPO_ROOT/backend"
FRONTEND_DIR="$REPO_ROOT/frontend"
TEST_DB="$BACKEND_DIR/finwise_test.db"

cleanup() {
    echo ""
    echo "Cleaning up..."
    [ -n "${BACKEND_PID:-}" ] && kill "$BACKEND_PID" 2>/dev/null || true
    [ -n "${FRONTEND_PID:-}" ] && kill "$FRONTEND_PID" 2>/dev/null || true
    rm -f "$TEST_DB"
    echo "Cleanup done."
}
trap cleanup EXIT

# Kill any existing processes on the ports
for port in 8000 5173; do
    pids=$(lsof -ti :"$port" 2>/dev/null || true)
    if [ -n "$pids" ]; then
        echo "Killing existing processes on port $port"
        echo "$pids" | xargs kill -9 2>/dev/null || true
    fi
done

# Remove stale test DB if it exists
rm -f "$TEST_DB"

# Start backend with test database
echo "Starting backend with test database..."
cd "$BACKEND_DIR"
source .venv/bin/activate
FINWISE_DATABASE_URL="sqlite:///./finwise_test.db" \
    uvicorn app.main:app --host 0.0.0.0 --port 8000 &
BACKEND_PID=$!

# Start frontend
echo "Starting frontend..."
cd "$FRONTEND_DIR"
npm run dev &
FRONTEND_PID=$!

# Wait for backend
echo "Waiting for backend..."
for i in $(seq 1 30); do
    if curl -sf --noproxy '*' http://127.0.0.1:8000/docs >/dev/null 2>&1; then
        echo "Backend ready."
        break
    fi
    if [ "$i" -eq 30 ]; then
        echo "ERROR: Backend failed to start within 30s"
        exit 1
    fi
    sleep 1
done

# Wait for frontend
echo "Waiting for frontend..."
for i in $(seq 1 30); do
    if curl -sf --noproxy '*' http://localhost:5173 >/dev/null 2>&1; then
        echo "Frontend ready."
        break
    fi
    if [ "$i" -eq 30 ]; then
        echo "ERROR: Frontend failed to start within 30s"
        exit 1
    fi
    sleep 1
done

# Run Cypress tests
echo "Running Cypress E2E tests..."
cd "$FRONTEND_DIR"
npx cypress run "$@"
