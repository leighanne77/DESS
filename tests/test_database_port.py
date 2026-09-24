"""DESS runs its own Postgres, on 5433 — never on the default 5432.

Another Postgres on the same machine very often holds 5432. When it did,
and DESS's own container was stopped, DESS's migrations connected to that
other server and got as far as a permission error. A demo tree must never
be one stopped container away from somebody else's database, so the port
is a contract, not a habit: every default names 5433, and no tracked file
points DESS at 5432.

Needs no database — it reads the files.
"""

import re
import subprocess
from configparser import ConfigParser
from pathlib import Path

import yaml

from app.config import Settings

REPO = Path(__file__).resolve().parent.parent
PORT = 5433

# A host-side 5432: a URL's `host:5432`, or a Compose mapping `"5432:…"`.
DEFAULT_PORT = re.compile(r"(?:localhost|127\.0\.0\.1):5432\b|[\"']?\b5432:\d+")


def _tracked_text_files() -> list[Path]:
    out = subprocess.run(
        ["git", "ls-files"], cwd=REPO, capture_output=True, text=True, check=True
    ).stdout.split()
    files = []
    for name in out:
        p = REPO / name
        try:
            p.read_text(encoding="utf-8")
        except (UnicodeDecodeError, IsADirectoryError, FileNotFoundError):
            continue
        files.append(p)
    return files


def test_compose_is_its_own_project_on_5433() -> None:
    compose = yaml.safe_load((REPO / "docker-compose.yml").read_text())
    assert compose.get("name") == "dess", "the Compose project must be named dess"
    ports = compose["services"]["db"]["ports"]
    assert ports == [f"{PORT}:5432"], f"db must publish host {PORT}, got {ports}"


def test_settings_defaults_name_5433() -> None:
    fields = Settings.model_fields
    for key in ("database_url", "test_database_url"):
        default = fields[key].default
        assert f"localhost:{PORT}/" in default, f"{key} default is {default}"


def test_alembic_ini_names_5433() -> None:
    ini = ConfigParser()
    ini.read(REPO / "alembic.ini")
    url = ini.get("alembic", "sqlalchemy.url")
    assert f"localhost:{PORT}/" in url, url


def test_env_example_names_5433() -> None:
    text = (REPO / ".env.example").read_text()
    assert f"localhost:{PORT}/dess" in text


def test_no_tracked_file_points_dess_at_5432() -> None:
    offenders = []
    for path in _tracked_text_files():
        if path == Path(__file__).resolve():
            continue
        for i, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            if DEFAULT_PORT.search(line):
                offenders.append(f"{path.relative_to(REPO)}:{i}  {line.strip()}")
    assert not offenders, "DESS must not use port 5432:\n" + "\n".join(offenders)


def test_ci_database_commands_name_5433() -> None:
    """`psql -h localhost` with no `-p` means 5432 — implicitly. The number
    never appears, so the scan above cannot see it; this does. It is the
    gap that turned CI red on the day the port moved."""
    ci = (REPO / ".github" / "workflows" / "ci.yml").read_text()
    offenders = [
        line.strip()
        for line in ci.splitlines()
        if re.search(r"\b(psql|createdb|dropdb|pg_dump|pg_restore)\b", line)
        and "-h localhost" in line
        and f"-p {PORT}" not in line
    ]
    assert not offenders, "CI database commands must say -p 5433:\n" + "\n".join(
        offenders
    )
