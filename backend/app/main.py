from __future__ import annotations

import asyncio
import json
from typing import AsyncIterator
from pathlib import Path
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, Request, status
from fastapi.responses import FileResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles

from backend.app.claude_cli import ClaudeCLISession, DONE_EVENT
from backend.app.config import AppConfig
from backend.app.models import ChatRequest, ResetRequest


BASE_DIR = Path(__file__).resolve().parent
STATIC_DIR = BASE_DIR / "static"


def _require_api_auth(request: Request) -> None:
    config = request.app.state.config
    if not config.auth_enabled:
        return

    auth_header = request.headers.get("authorization", "")
    expected = f"Bearer {config.api_token}"
    if auth_header != expected:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Unauthorized",
            headers={"WWW-Authenticate": "Bearer"},
        )

def create_app(session: ClaudeCLISession | None = None) -> FastAPI:
    config = AppConfig.from_env()

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        active_session = session or ClaudeCLISession(config)
        app.state.config = config
        app.state.claude_session = active_session
        await active_session.start()
        try:
            yield
        finally:
            await active_session.stop()

    app = FastAPI(title="Claude OAuth Chat Demo", lifespan=lifespan)
    app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")

    @app.get("/", include_in_schema=False)
    async def index() -> FileResponse:
        return FileResponse(STATIC_DIR / "index.html")

    @app.get("/health")
    async def health() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/api/status")
    async def status(request: Request) -> dict[str, object]:
        _require_api_auth(request)
        session_state = request.app.state.claude_session.status()
        session_state["allowed_models"] = request.app.state.config.claude_allowed_models
        session_state["auth_enabled"] = request.app.state.config.auth_enabled
        return session_state

    @app.post("/api/reset")
    async def reset(request: Request, body: ResetRequest) -> dict[str, object]:
        _require_api_auth(request)
        try:
            model = request.app.state.config.validate_model(body.model) if body.model else None
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

        await request.app.state.claude_session.reset(model)
        return request.app.state.claude_session.status()

    @app.post("/api/chat")
    async def chat(request: Request, body: ChatRequest) -> StreamingResponse:
        _require_api_auth(request)
        if body.model:
            try:
                request.app.state.config.validate_model(body.model)
            except ValueError as exc:
                raise HTTPException(status_code=400, detail=str(exc)) from exc

        text = body.messages[-1].content.strip()
        if not text:
            raise HTTPException(status_code=400, detail="Last message content is empty")

        events = await request.app.state.claude_session.send(text)

        async def event_stream() -> AsyncIterator[bytes]:
            try:
                while True:
                    event = await events.get()
                    if event == DONE_EVENT:
                        yield b"data: [DONE]\n\n"
                        break
                    yield f"data: {json.dumps(event)}\n\n".encode("utf-8")
            finally:
                request.app.state.claude_session.remove_queued(events)

        return StreamingResponse(
            event_stream(),
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache",
                "Connection": "keep-alive",
                "X-Accel-Buffering": "no",
            },
        )

    return app


app = create_app()
