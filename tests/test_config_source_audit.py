"""Tests for the startup env-var source audit."""

from __future__ import annotations

import logging
from pathlib import Path

from app.config import audit_config_sources, log_config_source_audit


def _write_env_file(path: Path, pairs: dict[str, str]) -> Path:
    """Write a minimal .env file for testing and return its path."""
    path.write_text("\n".join(f"{k}={v}" for k, v in pairs.items()) + "\n")
    return path


def test_env_var_source_wins_when_variable_is_set(tmp_path: Path) -> None:
    dotenv = _write_env_file(tmp_path / ".env", {"JWT_SECRET": "from-dotenv-1234"})
    records = audit_config_sources(
        names=["JWT_SECRET"],
        env={"JWT_SECRET": "from-shell-ABCD"},
        dotenv_path=dotenv,
    )
    assert len(records) == 1
    r = records[0]
    assert r["setting"] == "JWT_SECRET"
    assert r["source"] == "env_var"
    assert r["prefix"] == "from"
    assert r["suffix"] == "ABCD"


def test_dotenv_source_when_env_lacks_variable(tmp_path: Path) -> None:
    dotenv = _write_env_file(tmp_path / ".env", {"JWT_SECRET": "only-in-dotenv-XYZW"})
    records = audit_config_sources(
        names=["JWT_SECRET"],
        env={},
        dotenv_path=dotenv,
    )
    assert records[0]["source"] == "dotenv"
    assert records[0]["prefix"] == "only"
    assert records[0]["suffix"] == "XYZW"


def test_default_source_when_neither_env_nor_dotenv_has_it(tmp_path: Path) -> None:
    dotenv = _write_env_file(tmp_path / ".env", {"OTHER_KEY": "noise"})
    records = audit_config_sources(
        names=["JWT_SECRET"],
        env={},
        dotenv_path=dotenv,
    )
    assert records[0]["source"] == "default"
    assert records[0]["prefix"] == ""
    assert records[0]["suffix"] == ""


def test_cloud_run_labels_env_vars_as_secret_manager(tmp_path: Path) -> None:
    dotenv = _write_env_file(tmp_path / ".env", {})
    records = audit_config_sources(
        names=["JWT_SECRET"],
        env={"K_SERVICE": "dess-crm", "JWT_SECRET": "value-from-secret-4321"},
        dotenv_path=dotenv,
    )
    assert records[0]["source"] == "secret_manager"


def test_audit_covers_all_critical_settings(tmp_path: Path) -> None:
    dotenv = _write_env_file(tmp_path / ".env", {})
    records = audit_config_sources(
        env={
            "DATABASE_URL": "postgresql://a@b/c",
            "ANTHROPIC_API_KEY": "sk-ant-xxxx",
            "GOOGLE_CLIENT_ID": "id-val",
            "GOOGLE_CLIENT_SECRET": "gcs-val",
            "GOOGLE_REDIRECT_URI": "https://x/auth/callback",
            "JWT_SECRET": "jwt-val",
            "ALLOWED_EMAILS": "a@b.com,c@d.com",
            "TOKEN_ENCRYPTION_KEY": "fernet-key-val",
        },
        dotenv_path=dotenv,
    )
    names = [r["setting"] for r in records]
    assert names == [
        "DATABASE_URL",
        "ANTHROPIC_API_KEY",
        "GOOGLE_CLIENT_ID",
        "GOOGLE_CLIENT_SECRET",
        "GOOGLE_REDIRECT_URI",
        "JWT_SECRET",
        "ALLOWED_EMAILS",
        "TOKEN_ENCRYPTION_KEY",
    ]
    for r in records:
        assert r["source"] == "env_var"


def test_short_values_degrade_prefix_suffix_gracefully(tmp_path: Path) -> None:
    dotenv = _write_env_file(tmp_path / ".env", {})
    records = audit_config_sources(
        names=["JWT_SECRET"],
        env={"JWT_SECRET": "abc"},  # only 3 chars
        dotenv_path=dotenv,
    )
    assert records[0]["prefix"] == "abc"
    assert records[0]["suffix"] == ""


def test_log_emits_one_record_per_setting(caplog, tmp_path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    # Fresh .env with partial coverage: one setting in dotenv, rest default
    _write_env_file(tmp_path / ".env", {"JWT_SECRET": "jwt-only-in-dotenv"})
    # Clear any real env vars that might leak in from the developer's shell
    for name in (
        "DATABASE_URL",
        "ANTHROPIC_API_KEY",
        "GOOGLE_CLIENT_ID",
        "GOOGLE_CLIENT_SECRET",
        "GOOGLE_REDIRECT_URI",
        "JWT_SECRET",
        "ALLOWED_EMAILS",
        "TOKEN_ENCRYPTION_KEY",
        "K_SERVICE",
    ):
        monkeypatch.delenv(name, raising=False)

    with caplog.at_level(logging.INFO, logger="app.config"):
        log_config_source_audit()

    records = [r for r in caplog.records if r.getMessage() == "config_source_audit"]
    assert len(records) == 8
    jwt = next(r for r in records if r.setting == "JWT_SECRET")
    assert jwt.source == "dotenv"
    assert jwt.prefix == "jwt-"
    # All others have no env var and no dotenv entry → default
    for r in records:
        if r.setting != "JWT_SECRET":
            assert r.source == "default"
