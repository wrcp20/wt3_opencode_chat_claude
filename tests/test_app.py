from pathlib import Path
import sys
import asyncio

from fastapi.testclient import TestClient


sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from backend.app.claude_cli import DONE_EVENT
from backend.app.main import create_app


class FakeSession:
    def __init__(self) -> None:
        self.model = "claude-haiku-4-5-20251001"
        self.allowed_models = (
            "claude-haiku-4-5-20251001",
            "claude-sonnet-4-6",
            "claude-opus-4-6",
        )
        self.sent_messages: list[str] = []
        self.started = False
        self.stopped = False
        self.reset_calls: list[str | None] = []

    async def start(self) -> None:
        self.started = True

    async def stop(self) -> None:
        self.stopped = True

    async def send(self, text: str):
        self.sent_messages.append(text)
        queue: asyncio.Queue[dict[str, str]] = asyncio.Queue()
        await queue.put({"type": "text", "text": "Hola"})
        await queue.put({"type": "text", "text": " desde Claude"})
        await queue.put(DONE_EVENT)
        return queue

    def remove_queued(self, events) -> None:
        return None

    async def reset(self, model: str | None = None) -> None:
        self.reset_calls.append(model)
        if model:
            self.model = model

    def status(self) -> dict[str, object]:
        return {
            "ok": True,
            "model": self.model,
            "ready": True,
            "warming": False,
            "queue": 0,
        }


def make_client() -> tuple[TestClient, FakeSession]:
    session = FakeSession()
    app = create_app(session=session)
    return TestClient(app), session


def test_health() -> None:
    client, _ = make_client()
    with client:
        response = client.get("/health")

    assert response.status_code == 200
    assert response.json()["status"] == "ok"


def test_status() -> None:
    client, _ = make_client()
    with client:
        response = client.get("/api/status")

    assert response.status_code == 200
    payload = response.json()
    assert payload["ready"] is True
    assert payload["model"] == "claude-haiku-4-5-20251001"
    assert "claude-sonnet-4-6" in payload["allowed_models"]


def test_chat_streams_sse() -> None:
    client, session = make_client()
    with client:
        response = client.post(
            "/api/chat",
            json={"messages": [{"role": "user", "content": "Hola demo"}]},
        )

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/event-stream")
    assert 'data: {"type": "text", "text": "Hola"}' in response.text
    assert "data: [DONE]" in response.text
    assert session.sent_messages == ["Hola demo"]


def test_reset_changes_model() -> None:
    client, session = make_client()
    with client:
        response = client.post("/api/reset", json={"model": "claude-sonnet-4-6"})

    assert response.status_code == 200
    assert session.reset_calls == ["claude-sonnet-4-6"]
    assert response.json()["model"] == "claude-sonnet-4-6"


def test_api_requires_bearer_token_when_configured(monkeypatch) -> None:
    monkeypatch.setenv("API_TOKEN", "secret-demo-token")
    client, _ = make_client()
    with client:
        unauthorized = client.get("/api/status")
        authorized = client.get("/api/status", headers={"Authorization": "Bearer secret-demo-token"})

    assert unauthorized.status_code == 401
    assert unauthorized.json()["detail"] == "Unauthorized"
    assert authorized.status_code == 200
