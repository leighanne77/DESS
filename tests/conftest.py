"""Shared pytest fixtures.

Tests run against the dess_test database (separate from dev). One-time
setup outside this file:

    docker compose exec db createdb -U dess dess_test
    DATABASE_URL=postgresql+psycopg://dess:dess_dev_only@localhost:5432/dess_test \
        .venv/bin/alembic upgrade head

After that, the autouse `_apply_migrations` fixture keeps the schema
current on every test run.
"""

import os
import subprocess
from collections.abc import Callable, Generator

import pytest
from cryptography.fernet import Fernet
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

# A stable Fernet key for the whole test session. Must be set in
# os.environ BEFORE app.config is imported so the cached Settings
# singleton picks it up. The same value is also propagated to the
# Alembic subprocess that runs migrations.
os.environ.setdefault("TOKEN_ENCRYPTION_KEY", Fernet.generate_key().decode())

from app.config import get_settings  # noqa: E402
from app.database import get_db  # noqa: E402
from app.main import app  # noqa: E402
from app.models import User  # noqa: E402


@pytest.fixture(scope="session")
def engine() -> Generator[Engine, None, None]:
    """Engine bound to the test database for the whole session."""
    eng = create_engine(get_settings().test_database_url, pool_pre_ping=True)
    yield eng
    eng.dispose()


@pytest.fixture(scope="session", autouse=True)
def _apply_migrations(engine: Engine) -> None:
    """Bring the test DB schema up to Alembic head before any test runs.

    Uses `sys.executable -m alembic` so this works in any environment
    where alembic is importable by the running Python — local .venv,
    CI (system Python after pip install), or anywhere in between.
    Avoids hardcoded paths to `.venv/bin/alembic`.
    """
    import sys

    env = os.environ.copy()
    env["DATABASE_URL"] = get_settings().test_database_url
    repo_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    subprocess.run(
        [sys.executable, "-m", "alembic", "upgrade", "head"],
        check=True,
        env=env,
        cwd=repo_root,
    )


@pytest.fixture
def db(engine: Engine) -> Generator[Session, None, None]:
    """Truncate tables, then yield a fresh session for the test."""
    with engine.begin() as conn:
        conn.execute(
            text(
                "TRUNCATE TABLE audit_log, change_requests, contacts, users "
                "RESTART IDENTITY CASCADE"
            )
        )
    SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()


@pytest.fixture
def client(db: Session) -> Generator[TestClient, None, None]:
    """TestClient with get_db wired to the test session."""

    def _override_get_db() -> Generator[Session, None, None]:
        yield db

    app.dependency_overrides[get_db] = _override_get_db
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()


@pytest.fixture
def user_factory(db: Session) -> Callable[..., User]:
    """Create users with auto-incrementing distinct emails."""
    counter = {"n": 0}

    def _make(**overrides: object) -> User:
        counter["n"] += 1
        n = counter["n"]
        defaults: dict[str, object] = {
            "email": f"user{n}@test.fake",
            "name": f"Test User {n}",
            "google_user_id": f"test-google-id-{n}",
            "intro_seen": False,
        }
        defaults.update(overrides)
        user = User(**defaults)  # type: ignore[arg-type]
        db.add(user)
        db.commit()
        db.refresh(user)
        return user

    return _make
