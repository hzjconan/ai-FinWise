#!/usr/bin/env bash
set -euo pipefail

TARGET="${1:-all}"
if [[ "$TARGET" == "admin" || "$TARGET" == "customer" || "$TARGET" == "all" ]]; then
    shift || true
fi

REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
BACKEND_DIR="$REPO_ROOT/backend"
ADMIN_DIR="$REPO_ROOT/frontend-admin"
CUSTOMER_DIR="$REPO_ROOT/frontend-customer"
TEST_DB="$BACKEND_DIR/finwise_test.db"

cleanup() {
    echo ""
    echo "Cleaning up..."
    [ -n "${BACKEND_PID:-}" ] && kill "$BACKEND_PID" 2>/dev/null || true
    [ -n "${ADMIN_PID:-}" ] && kill "$ADMIN_PID" 2>/dev/null || true
    [ -n "${CUSTOMER_PID:-}" ] && kill "$CUSTOMER_PID" 2>/dev/null || true
    rm -f "$TEST_DB"
    echo "Cleanup done."
}
trap cleanup EXIT

# Kill any existing processes on the ports
for port in 8000 5173 5174; do
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
FINWISE_DATABASE_URL="sqlite:///./finwise_test.db" alembic upgrade head
FINWISE_DATABASE_URL="sqlite:///./finwise_test.db" \
    uvicorn app.main:app --host 0.0.0.0 --port 8000 &
BACKEND_PID=$!

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

EXIT_CODE=0

# Run admin tests
if [[ "$TARGET" == "admin" || "$TARGET" == "all" ]]; then
    echo "Starting admin frontend (port 5174)..."
    cd "$ADMIN_DIR"
    npm run dev &
    ADMIN_PID=$!

    echo "Waiting for admin frontend..."
    for i in $(seq 1 30); do
        if curl -sf --noproxy '*' http://localhost:5174 >/dev/null 2>&1; then
            echo "Admin frontend ready."
            break
        fi
        if [ "$i" -eq 30 ]; then
            echo "ERROR: Admin frontend failed to start within 30s"
            exit 1
        fi
        sleep 1
    done

    echo "Running admin Cypress tests..."
    cd "$ADMIN_DIR"
    npx cypress run "$@" || EXIT_CODE=$?

    kill "$ADMIN_PID" 2>/dev/null || true
    ADMIN_PID=""
fi

# Run customer tests
if [[ "$TARGET" == "customer" || "$TARGET" == "all" ]]; then
    # 若先跑过 admin 套件，admin 会在共享的测试 DB 中留下 15+ 产品（包括 12 个 PAG-XXX
    # 分页测试产品）。customer 端依赖 /products 和 /products/hot 返回新种的产品，
    # 但所有 seed 产品具有相同的 expected_return / risk_level，排序时并列导致新产品挤不进
    # 首页或热门列表。这里在两套件之间重启 backend、清空 DB 以隔离测试数据。
    if [[ "$TARGET" == "all" ]]; then
        echo "Resetting test database between admin and customer suites..."
        kill "$BACKEND_PID" 2>/dev/null || true
        wait "$BACKEND_PID" 2>/dev/null || true
        rm -f "$TEST_DB"
        cd "$BACKEND_DIR"
        source .venv/bin/activate
        FINWISE_DATABASE_URL="sqlite:///./finwise_test.db" \
            uvicorn app.main:app --host 0.0.0.0 --port 8000 &
        BACKEND_PID=$!
        for i in $(seq 1 30); do
            if curl -sf --noproxy '*' http://127.0.0.1:8000/docs >/dev/null 2>&1; then
                echo "Backend ready (fresh DB)."
                break
            fi
            if [ "$i" -eq 30 ]; then
                echo "ERROR: Backend failed to restart within 30s"
                exit 1
            fi
            sleep 1
        done
    fi

    echo "Starting customer frontend (port 5173)..."
    cd "$CUSTOMER_DIR"
    npm run dev &
    CUSTOMER_PID=$!

    echo "Waiting for customer frontend..."
    for i in $(seq 1 30); do
        if curl -sf --noproxy '*' http://localhost:5173 >/dev/null 2>&1; then
            echo "Customer frontend ready."
            break
        fi
        if [ "$i" -eq 30 ]; then
            echo "ERROR: Customer frontend failed to start within 30s"
            exit 1
        fi
        sleep 1
    done

    echo "Running customer Cypress tests..."
    cd "$CUSTOMER_DIR"
    npx cypress run "$@" || EXIT_CODE=$?

    kill "$CUSTOMER_PID" 2>/dev/null || true
    CUSTOMER_PID=""
fi

exit $EXIT_CODE
