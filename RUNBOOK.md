# DESS runbook — how it is set up, and what to type when

Everything here runs from a terminal in the DESS folder. No agent needed.
The demo dataset is the only dataset: nothing here touches real data.

## How it is put together

| Piece | What it is | Where it runs |
|---|---|---|
| Database | Postgres 15 in Docker, Compose project `dess`, data kept in the volume `dess_pgdata` | `localhost:5434` (not 5432 or 5433 — see below) |
| Databases inside it | `dess` (the app) and `dess_test` (the tests; wiped by every test run) | same server |
| Backend | FastAPI app in `app/`, schema changes in `alembic/` | `http://localhost:8000` |
| Frontend | React + Vite in `frontend/` | `http://localhost:5173` (forwards `/api` to 8000) |
| Python environment | `.venv/` in the repo folder, Python 3.11 or newer | — |
| Settings | `.env` (copied from `.env.example`, never committed) | — |

**Why port 5434.** Other Postgres servers on the same machine usually take
5432, and 5433 is where a second Postgres or a Cloud SQL Auth Proxy tunnel
conventionally listens. DESS stays off both, so it can never connect to
someone else's database by mistake, and never sits on a port another tool
expects to be its own tunnel. `tests/test_database_port.py` fails if
anything moves it back.

**Moving from 5433.** A container started before this change still
publishes 5433. Recreate it with `docker compose up -d db`: the data
survives, because the volume is named by the Compose project, not the
port. A local `.env` copied earlier needs its `5433` changed to `5434`.

## Once — first-time setup

```bash
# 1. The database (permanent: it survives restarts)
docker compose up -d db
docker compose exec db createdb -U dess dess_test

# 2. Python — name the version; plain `python3` on a Mac may be too old
/opt/homebrew/bin/python3.12 -m venv .venv
.venv/bin/pip install --upgrade pip
.venv/bin/pip install -e ".[dev]"

# 3. Settings — then add your Anthropic key to .env to enable chat
cp .env.example .env

# 4. Schema and demo data
.venv/bin/alembic upgrade head
.venv/bin/python -m scripts.seed_dummy_data

# 5. Frontend packages
cd frontend && npm ci && cd ..

# 6. Commit hooks (black, isort, flake8, prettier)
.venv/bin/pre-commit install
```

## Every time you work on it

```bash
open -a Docker                  # if Docker Desktop is not running
docker compose up -d db         # start the database (safe if already up)
make backend                    # terminal 1 — API on :8000
make frontend                   # terminal 2 — app on :5173
```

Open `http://localhost:5173`. Check the API alone with
`curl http://localhost:8000/api/health` — it answers
`{"status":"ok","enterprise_mode":false}`.

To stop: `Ctrl-C` in each terminal, then `docker compose stop db`.
`stop` keeps the data; see the warning under **Resetting**.

## Before you commit

```bash
make test                       # the whole backend suite (needs the db up)
cd frontend && npm run build && npm run lint && cd ..
git status                      # nothing you did not mean to add
```

Then commit. The hooks format and lint for you; if a hook rewrites a
file, `git add` it and commit again.

## When you change something specific

| You changed… | Run |
|---|---|
| a model in `app/models/` (a column or table) | `.venv/bin/alembic revision --autogenerate -m "what changed"`, read the file it wrote, then `.venv/bin/alembic upgrade head` |
| a Pydantic schema the frontend uses | `make sync-types` and commit `frontend/src/api/generated_types.ts` |
| an icon in `frontend/src/assets/brand-icons/` | `make sync-icon-names` |
| a flag in `frontend/src/assets/country-flags/` | `make sync-country-codes` |
| the chat prompt, the tool loop, or anything that feeds text to the model | the evals — below |
| `app/policies.yaml` | bump its `version:`, then `make test` |

## The evals — the model's behaviour, not the code's

They make real Claude calls (a few cents a run), so they run by hand, not
on every commit.

```bash
.venv/bin/python evals/export_system_prompt.py
export ANTHROPIC_API_KEY=...    # the same key as in .env
cd evals && npx promptfoo@latest eval && npx promptfoo@latest view
```

## Resetting

```bash
.venv/bin/python -m scripts.seed_dummy_data --reset   # wipe contacts, re-seed
docker compose down                                   # stop and remove the container; data kept
docker compose down -v                                # ALSO DELETES THE DATA — then redo "Once" steps 1 and 4
```

## When something breaks

| Symptom | Cause | Fix |
|---|---|---|
| `connection refused` on 5434 | the database is not running | `docker compose up -d db` |
| `Cannot connect to the Docker daemon` | Docker Desktop is closed or signed out | open Docker Desktop, sign in, retry |
| tests fail with `database "dess_test" does not exist` | first run on a new volume | `docker compose exec db createdb -U dess dess_test` |
| `NoSuchTableError` in a test that uses the app database | `dess` was never migrated | `.venv/bin/alembic upgrade head` |
| `address already in use` on 8000 or 5173 | an old server is still running | `make backend` / `make frontend` kill the old one first |
| `pip` says the package needs Python 3.11 | the venv was built with an old Python | `rm -rf .venv`, redo "Once" step 2 |
| a moved or renamed folder and `.venv/bin/...` fails | a venv stores its own absolute path | `rm -rf .venv`, redo "Once" step 2 |
| `pre-commit not found` on commit | the hook runs from the venv | use `.venv/bin/...`; never skip the hook |
| chat fails, the rest of the app works | no Anthropic key in `.env` | add `ANTHROPIC_API_KEY` to `.env`, restart `make backend` |

## What is known to be red

- `tests/test_enterprise_mode_guard.py::test_guard_blocks_real_email_in_tool_result`
  fails: its "real" address was changed to a `.fake` one, which the guard
  correctly lets through. A fix is planned. Until then `make test` shows
  one failure, and CI is red for the same reason.
