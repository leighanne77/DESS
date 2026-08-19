"""Tests for the OAuth login flow.

Both Google calls are mocked: the token-exchange POST and the ID-token
verification. The state-cookie roundtrip uses the real TestClient
cookie jar so the same flow a real browser does is exercised.
"""

from typing import Any, Callable

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.models import User
from app.routers import auth as auth_router

ALLOWED = "pat@example.com,robin@example.com"


@pytest.fixture
def configured_oauth(monkeypatch: pytest.MonkeyPatch) -> None:
    settings = get_settings()
    monkeypatch.setattr(settings, "google_client_id", "test-client-id")
    monkeypatch.setattr(settings, "google_client_secret", "test-secret")
    monkeypatch.setattr(settings, "allowed_emails", ALLOWED)


@pytest.fixture
def fake_google(
    monkeypatch: pytest.MonkeyPatch, configured_oauth: None
) -> dict[str, Any]:
    """Mock Google: code-exchange returns a fake token, verify returns claims.

    Tests can mutate the returned dict to control which email comes back.
    """
    state: dict[str, Any] = {
        "email": "robin@example.com",
        "sub": "google-user-1",
        "name": "Alice Tester",
    }

    async def fake_exchange(code: str) -> tuple[str, str | None, str | None]:
        # Returns (id_token, access_token, refresh_token). Day 5 added
        # access_token so the callback can capture the Google token for
        # later Sheets/Drive calls. Day 6 added refresh_token so the
        # sheets service can swap an expired/revoked access_token for a
        # fresh one without bouncing the user back to OAuth.
        return (
            f"fake-id-token-for-{code}",
            f"fake-access-token-for-{code}",
            f"fake-refresh-token-for-{code}",
        )

    async def fake_verify(id_token: str) -> dict[str, Any]:
        return dict(state)

    monkeypatch.setattr(auth_router, "_exchange_code_for_tokens", fake_exchange)
    monkeypatch.setattr(auth_router, "verify_google_id_token", fake_verify)
    return state


def _begin_login(client: TestClient) -> str:
    """Hit /auth/google to plant the state cookie. Return the state value."""
    resp = client.get("/api/auth/google", follow_redirects=False)
    assert resp.status_code == 307
    assert resp.headers["location"].startswith(
        "https://accounts.google.com/o/oauth2/v2/auth?"
    )
    state = resp.cookies.get("oauth_state")
    assert state, "oauth_state cookie was not set"
    return state


def test_callback_happy_path_sets_session_cookie_and_redirects(
    client: TestClient,
    db: Session,
    fake_google: dict[str, Any],
) -> None:
    state = _begin_login(client)
    resp = client.get(
        "/api/auth/callback",
        params={"code": "abc123", "state": state},
        follow_redirects=False,
    )
    assert resp.status_code == 303
    assert resp.headers["location"].endswith("/auth/success")
    cookie = resp.cookies.get("dess_session")
    assert cookie, "dess_session cookie was not set"

    user = db.scalars(select(User).where(User.email == "robin@example.com")).first()
    assert user is not None
    assert user.last_login is not None
    # Day 6: both access_token and refresh_token are captured from the
    # OAuth code exchange and persisted to the users row, so the Sheets
    # service can self-refresh without bouncing back to OAuth.
    assert user.google_access_token == "fake-access-token-for-abc123"
    assert user.google_refresh_token == "fake-refresh-token-for-abc123"


def test_oauth_start_requests_offline_access_and_consent_prompt(
    client: TestClient,
) -> None:
    """Day 6 regression guard. Without access_type=offline + prompt=
    consent, Google won't return a refresh_token — and the whole
    self-refresh story above silently reverts to the old one-shot
    Day 5 behavior. Pin the query-string contract."""
    resp = client.get("/api/auth/google", follow_redirects=False)
    assert resp.status_code == 307
    location = resp.headers["location"]
    assert "access_type=offline" in location
    assert "prompt=consent" in location


def test_callback_preserves_existing_refresh_token_when_google_omits_one(
    client: TestClient,
    db: Session,
    configured_oauth: None,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Day 6 regression guard. Google only returns refresh_token on
    consent; a later sign-in without fresh consent gets access_token
    only. We must NOT wipe the existing refresh_token in that case."""
    from app.routers import auth as auth_router
    from app.services.google_oauth import verify_google_id_token  # noqa: F401

    claims = {
        "email": "robin@example.com",
        "sub": "google-user-1",
        "name": "Alice Tester",
    }

    async def exchange_with_refresh(code: str):
        return (
            f"fake-id-token-for-{code}",
            "access-1",
            "refresh-1",
        )

    async def exchange_without_refresh(code: str):
        return (
            f"fake-id-token-for-{code}",
            "access-2",
            None,
        )

    async def fake_verify(_id_token: str):
        return dict(claims)

    monkeypatch.setattr(auth_router, "verify_google_id_token", fake_verify)

    # First login — gets both tokens.
    monkeypatch.setattr(auth_router, "_exchange_code_for_tokens", exchange_with_refresh)
    state1 = _begin_login(client)
    client.get(
        "/api/auth/callback",
        params={"code": "login1", "state": state1},
        follow_redirects=False,
    )
    user = db.scalars(select(User).where(User.email == claims["email"])).first()
    assert user is not None
    assert user.google_refresh_token == "refresh-1"

    # Second login — Google omits refresh_token. Ours must survive.
    monkeypatch.setattr(
        auth_router, "_exchange_code_for_tokens", exchange_without_refresh
    )
    state2 = _begin_login(client)
    client.get(
        "/api/auth/callback",
        params={"code": "login2", "state": state2},
        follow_redirects=False,
    )
    db.refresh(user)
    assert user.google_access_token == "access-2"
    assert user.google_refresh_token == "refresh-1"  # preserved, not overwritten


def test_session_cookie_authenticates_subsequent_requests(
    client: TestClient,
    fake_google: dict[str, Any],
) -> None:
    """Cookie set by the callback should let /api/users/me succeed."""
    state = _begin_login(client)
    callback = client.get(
        "/api/auth/callback",
        params={"code": "abc123", "state": state},
        follow_redirects=False,
    )
    assert callback.status_code == 303
    # TestClient cookie jar carries the session cookie forward automatically.
    me = client.get("/api/users/me")
    assert me.status_code == 200
    assert me.json()["email"] == "robin@example.com"


def test_callback_state_mismatch_returns_400(
    client: TestClient, fake_google: dict[str, Any]
) -> None:
    _begin_login(client)
    resp = client.get(
        "/api/auth/callback",
        params={"code": "abc123", "state": "definitely-not-the-real-state"},
    )
    assert resp.status_code == 400


def test_callback_unauthorized_email_returns_403(
    client: TestClient, fake_google: dict[str, Any]
) -> None:
    state = _begin_login(client)
    fake_google["email"] = "stranger@example.com"
    resp = client.get("/api/auth/callback", params={"code": "abc123", "state": state})
    assert resp.status_code == 403


def test_callback_existing_user_does_not_duplicate(
    client: TestClient,
    db: Session,
    user_factory: Callable[..., User],
    fake_google: dict[str, Any],
) -> None:
    existing = user_factory(email="robin@example.com")

    state = _begin_login(client)
    resp = client.get(
        "/api/auth/callback",
        params={"code": "abc123", "state": state},
        follow_redirects=False,
    )
    assert resp.status_code == 303

    matches = list(
        db.scalars(select(User).where(User.email == "robin@example.com"))
    )
    assert len(matches) == 1
    assert matches[0].id == existing.id


def test_callback_without_state_cookie_returns_400(
    client: TestClient, fake_google: dict[str, Any]
) -> None:
    """Bypass /auth/google entirely; callback must reject."""
    resp = client.get(
        "/api/auth/callback", params={"code": "abc123", "state": "anything"}
    )
    assert resp.status_code == 400
