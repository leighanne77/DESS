"""The Help agent — how-to answers with NO tools and no CRM access."""

from typing import Any, Callable

import pytest
from fastapi.testclient import TestClient

from app.models import User
from app.security import create_access_token
from app.services import llm


def test_help_requires_auth(client: TestClient) -> None:
    assert client.post("/api/help", json={"question": "hi"}).status_code == 401


def test_help_answers_from_guide_with_no_tools(
    client: TestClient,
    user_factory: Callable[..., User],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    user = user_factory()
    seen: dict[str, Any] = {}

    async def fake_call(**kwargs: Any):
        seen.update(kwargs)

        class Block:
            type = "text"
            text = "Tap the mic, talk, tap again."

        class Msg:
            content = [Block()]

        return Msg()

    monkeypatch.setattr(llm, "call_claude", fake_call)
    resp = client.post(
        "/api/help",
        json={"question": "how do I use the microphone?"},
        headers={"Authorization": f"Bearer {create_access_token(user_id=user.id)}"},
    )
    assert resp.status_code == 200
    assert "mic" in resp.json()["answer"]
    # The trust property: the Help agent is never given tools.
    assert seen.get("tools") is None
    assert "THE GUIDE" in seen["system"]
