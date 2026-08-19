"""Shared FastAPI dependencies.

get_current_user is the gate every protected endpoint goes through.
It accepts EITHER:
  - a session cookie (the browser flow set by /auth/callback), OR
  - an Authorization: Bearer header (the CLI flow used by tests and
    scripts/test_chat.py)

Both paths converge on a JWT, decoded by app.security.decode_access_token.
Failures of any kind raise 401 — endpoints don't need to disambiguate.
"""

from fastapi import Cookie, Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from sqlalchemy.orm import Session

from app.config import get_settings
from app.database import get_db
from app.models import User
from app.security import decode_access_token

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="auth/google", auto_error=False)

_unauthorized = HTTPException(
    status_code=status.HTTP_401_UNAUTHORIZED,
    detail="Not authenticated",
    headers={"WWW-Authenticate": "Bearer"},
)


def get_current_user(
    bearer_token: str | None = Depends(oauth2_scheme),
    dess_session: str | None = Cookie(default=None),
    db: Session = Depends(get_db),
) -> User:
    """Return the current user from cookie or Bearer header, else 401."""
    # Cookie's actual name is configured in Settings, but FastAPI's Cookie()
    # binds by parameter name. We use `dess_session` matching the default;
    # if the setting is overridden in tests, look it up directly.
    settings = get_settings()
    if settings.session_cookie_name != "dess_session":
        # Edge case for tests that rename the cookie — not a runtime concern.
        dess_session = None

    token = bearer_token or dess_session
    if not token:
        raise _unauthorized
    user_id = decode_access_token(token)
    if user_id is None:
        raise _unauthorized
    user = db.get(User, user_id)
    if user is None:
        raise _unauthorized
    return user


def require_admin(current_user: User = Depends(get_current_user)) -> User:
    """Gate endpoints to admin users. Non-admins get 403.

    System roles are coarse (admin / member) and control UI access —
    the audit log UI uses this; Phase 2 review queue may as well.
    Functional roles (Administrator / Strategy Lead / etc.) are a
    separate concept, kept in seed data for now.
    """
    if current_user.role != "admin":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Admin role required.",
        )
    return current_user
