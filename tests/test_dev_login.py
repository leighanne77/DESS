"""Tests for the local-only dev sign-in.

The one invariant that matters: dev-login must be invisible (404) when
ENTERPRISE_MODE is on, so it can never grant a session in production.
Locally it issues a normal session for an allowlisted email.
"""

from fastapi.testclient import TestClient

from app.config import get_settings
from app.models import User


def test_dev_login_issues_session_when_not_enterprise(
    client: TestClient, monkeypatch
) -> None:
    settings = get_settings()
    monkeypatch.setattr(settings, "enterprise_mode", False)
    monkeypatch.setattr(settings, "allowed_emails", "dev@example.com")

    # Don't follow the redirect to the frontend; we just want the cookie.
    resp = client.get("/api/auth/dev-login", follow_redirects=False)
    assert resp.status_code == 303
    assert settings.session_cookie_name in resp.cookies


def test_dev_login_creates_allowlisted_user(
    client: TestClient, db, monkeypatch
) -> None:
    settings = get_settings()
    monkeypatch.setattr(settings, "enterprise_mode", False)
    monkeypatch.setattr(settings, "allowed_emails", "dev@example.com")

    client.get("/api/auth/dev-login", follow_redirects=False)

    user = db.query(User).filter(User.email == "dev@example.com").first()
    assert user is not None
    assert user.google_user_id == "dev-local:dev@example.com"


def test_dev_login_rejects_email_off_allowlist(client: TestClient, monkeypatch) -> None:
    settings = get_settings()
    monkeypatch.setattr(settings, "enterprise_mode", False)
    monkeypatch.setattr(settings, "allowed_emails", "dev@example.com")

    resp = client.get(
        "/api/auth/dev-login",
        params={"email": "intruder@evil.fake"},
        follow_redirects=False,
    )
    assert resp.status_code == 403


def test_dev_login_is_404_under_enterprise_mode(
    client: TestClient, monkeypatch
) -> None:
    settings = get_settings()
    monkeypatch.setattr(settings, "enterprise_mode", True)

    resp = client.get("/api/auth/dev-login", follow_redirects=False)
    assert resp.status_code == 404
