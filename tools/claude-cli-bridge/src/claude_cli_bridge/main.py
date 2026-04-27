"""claude-cli-bridge 主应用。

启动：
  uvicorn claude_cli_bridge.main:app --port 8787

业务后端把 ANTHROPIC_BASE_URL 指向这里（例如 http://localhost:8787，不带 /v1），即可让
Anthropic SDK 的请求路由到本地 Claude CLI。
"""
from fastapi import FastAPI

from claude_cli_bridge.messages import router as messages_router

app = FastAPI(title="Claude CLI Bridge", version="0.1.0")

app.include_router(messages_router, prefix="/v1")


@app.get("/healthz")
def healthz():
    return {"status": "ok"}
