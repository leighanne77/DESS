"""Tests for /users endpoints."""

from typing import Callable

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.models import User
from app.security import create_access_token


def _auth_headers(user: User) -> dict[str, str]:
    return {"Authorization": f"Bearer {create_access_token(user_id=user.id)}"}


def test_intro_seen_flips_from_false_to_true(
    client: TestClient,
    db: Session,
    user_factory: Callable[..., User],
) -> None:
    user = user_factory(intro_seen=False)
    assert user.intro_seen is False

    resp = client.patch("/api/users/me/intro-seen", headers=_auth_headers(user))
    assert resp.status_code == 204

    db.refresh(user)
    assert user.intro_seen is True


def test_users_me_returns_current_user(
    client: TestClient,
    user_factory: Callable[..., User],
) -> None:
    user = user_factory(email="who@test.fake", name="Whoever", intro_seen=True)
    resp = client.get("/api/users/me", headers=_auth_headers(user))
    assert resp.status_code == 200
    body = resp.json()
    assert body["email"] == "who@test.fake"
    assert body["name"] == "Whoever"
    assert body["intro_seen"] is True
    assert body["role"] == "member"
    # No internal token-budget fields leak.
    assert "daily_input_tokens_used" not in body


def test_users_me_requires_auth(client: TestClient) -> None:
    resp = client.get("/api/users/me")
    assert resp.status_code == 401


def test_logout_clears_session_cookie(client: TestClient) -> None:
    resp = client.post("/api/auth/logout")
    assert resp.status_code == 204
    set_cookie = resp.headers.get("set-cookie", "")
    assert "dess_session" in set_cookie
    # Browser interprets max-age=0 or expires in the past as deletion.
    assert "max-age=0" in set_cookie.lower() or "expires=" in set_cookie.lower()
