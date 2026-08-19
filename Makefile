.PHONY: sync-types sync-types-check sync-icon-names sync-icon-names-check sync-country-codes sync-country-codes-check test backend frontend docker-local docker-push cloud-push cloud-deploy

# --- Docker image config (override on the command line, e.g. make docker-push TAG=slice7.2) ---
AR_REGION ?= us-west1
AR_PROJECT ?= your-gcp-project
AR_REPO ?= dess-crm
IMAGE_NAME ?= backend
TAG ?= $(shell git rev-parse --short HEAD)
IMAGE_URI = $(AR_REGION)-docker.pkg.dev/$(AR_PROJECT)/$(AR_REPO)/$(IMAGE_NAME):$(TAG)

# Regenerate frontend TypeScript types from Pydantic models.
# Needs frontend/node_modules/.bin/json2ts on PATH — make sure you've run
# `npm ci` in frontend/ first.
sync-types:
	.venv/bin/python scripts/sync_types.py

# CI check: regenerate and fail if the committed file differs. Catches
# forgotten regenerations before they reach main.
sync-types-check: sync-types
	@git diff --exit-code frontend/src/api/generated_types.ts || \
		(echo "ERROR: generated_types.ts is out of sync. Run 'make sync-types' and commit." && exit 1)

# Regenerate the BrandIconName Literal union from the SVG directory.
# Must be re-run after adding/removing an icon in
# frontend/src/assets/brand-icons/ so the compiler knows the new name.
sync-icon-names:
	.venv/bin/python scripts/sync_icon_names.py

# CI check: regenerate and fail if the committed file differs.
sync-icon-names-check: sync-icon-names
	@git diff --exit-code frontend/src/components/brandIconNames.ts || \
		(echo "ERROR: brandIconNames.ts is out of sync. Run 'make sync-icon-names' and commit." && exit 1)

# Regenerate the CountryCode Literal union from the country-flags SVG
# directory. Run after adding/removing a flag in
# frontend/src/assets/country-flags/ so the compiler knows the new code.
sync-country-codes:
	.venv/bin/python scripts/sync_country_codes.py

# CI check: regenerate and fail if the committed file differs.
sync-country-codes-check: sync-country-codes
	@git diff --exit-code frontend/src/components/countryCodes.ts || \
		(echo "ERROR: countryCodes.ts is out of sync. Run 'make sync-country-codes' and commit." && exit 1)

test:
	.venv/bin/python -m pytest tests/ -q

# Kill any stale uvicorn process holding port 8000, then start fresh.
# Addresses the Day 4 smoke-session friction.
backend:
	-pkill -f 'uvicorn.*app.main' 2>/dev/null || true
	unset ANTHROPIC_API_KEY && .venv/bin/uvicorn app.main:app --reload

# Kill any stale Vite dev server, then start fresh.
frontend:
	-pkill -f 'vite' 2>/dev/null || true
	cd frontend && npm run dev

# Local arm64 build for Apple Silicon dev iteration. Loads into the
# local Docker daemon so `docker run dess-crm:dev` works immediately.
# Single-platform — multi-arch images can't be --load'ed, only --push'ed.
docker-local:
	docker buildx build --platform linux/arm64 -t dess-crm:dev --load .

# Multi-arch prod build (amd64 + arm64) pushed to Artifact Registry.
# Override TAG to use a non-hash tag, e.g. `make docker-push TAG=slice7.2`.
# After push, deploy with: gcloud run services update dess-crm \
#   --region=$(AR_REGION) --project=$(AR_PROJECT) --image=$(IMAGE_URI)
#
# NOTE: on Apple Silicon this emulates amd64 (slow). Prefer `cloud-push` /
# `cloud-deploy` below, which build natively on Cloud Build.
docker-push:
	@echo "Pushing $(IMAGE_URI)"
	docker buildx build --platform linux/amd64,linux/arm64 -t $(IMAGE_URI) --push .

# Build the prod image on Cloud Build (native amd64 — no local QEMU emulation)
# and push to Artifact Registry. Faster than docker-push on Apple Silicon and
# frees your machine. Override TAG as with docker-push.
cloud-push:
	gcloud builds submit --config cloudbuild.yaml --project=$(AR_PROJECT) \
	  --substitutions=_TAG=$(TAG),_REPO=$(AR_REPO),_IMAGE=$(IMAGE_NAME),_REGION=$(AR_REGION)

# One-shot: build on Cloud Build, then roll out the new revision to Cloud Run.
# Startup runs `alembic upgrade head` before serving.
cloud-deploy: cloud-push
	gcloud run services update dess-crm \
	  --region=$(AR_REGION) --project=$(AR_PROJECT) --image=$(IMAGE_URI)
