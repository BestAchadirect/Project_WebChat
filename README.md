# Project WebChat (AchaDirect)

## Business Overview
Project WebChat is AchaDirect's AI-assisted customer chat experience that turns your knowledge base and Magento catalog into accurate, guided conversations. It helps teams answer customer questions, find matching products, and route requests to the right flow, without manual chat scripts.

## Current Scope
- Magento-only product direction
- Single-store direction
- Read-only AI assistant
- Product discovery
- Product recommendation
- FAQ / policy answering
- Structured frontend rendering

## Current Data Strategy
- Current upstream product source: Klevu API
- Future upstream product source: Magento API
- AI serving layer: local PostgreSQL database

The intended runtime shape is:
1. External system syncs into local storage
2. Backend services read local data
3. AI tools call backend services
4. LLM orchestrates tool usage

### Who it is for
- AchaDirect ecommerce and support teams
- Product or operations teams that need reliable AI answers tied to real data
- Business owners who want measurable conversion from chat interactions

### Key benefits
- Faster answers with consistent tone and guardrails
- Better product discovery and matching
- Lower support load with automated, accurate responses
- Clear controls for content, routing, and analytics

### Core capabilities
- Knowledge base import (CSV) -> chunking -> embeddings -> RAG answers
- Magento product import (CSV) -> product embeddings -> product carousel in chat
- Structured chat runtime with routing, retrieval, grounded response composition, and an emerging tool-calling path

### Current highlights
- Smart product search
  - Exact SKU match and master code grouping
  - AI code detection from natural language
  - Semantic fallback when exact match is not found
  - Carousel limit increased to 10 products
- Interactive banner carousel for the chat greeting
- Dynamic, context-aware quick replies

## Technical Overview
FastAPI + PostgreSQL (pgvector) backend with a React admin dashboard.

## Key Docs
- Repo structure and placement rules: [AGENTS.md](./AGENTS.md)
- AI implementation guidance: [docs/ai/agent-implementation-plan.md](./docs/ai/agent-implementation-plan.md)
- Backend setup and backend-specific notes: [backend/README.md](./backend/README.md)

## Project Structure
See `AGENTS.md` for the canonical directory structure and responsibilities.

Quick view:

```
Project_WebChat/
  backend/                # FastAPI backend
  frontend-admin/         # React admin UI
  shared/                 # Shared types and utilities
  docs/                   # Architecture notes and guides
  infra/                  # Infrastructure and deployment
  tests/                  # Reserved for cross-service/e2e tests
```

Useful docs:
- AI implementation plan: `docs/ai/agent-implementation-plan.md`
- Backend guide: `backend/README.md`

Note:
- Older references to a broader `docs/` tree may be stale in the current worktree. Use `AGENTS.md`, this `README.md`, and `docs/ai/agent-implementation-plan.md` as the current top-level guidance.

## Quick start

### One-command dev (PowerShell)
From the repo root:

```powershell
.\dev.ps1
```

With a public ngrok URL (admin UI + API proxy):

```powershell
.\dev.ps1 -Ngrok
```

### Backend

```bash
cd backend
python -m venv .venv
.\.venv\Scripts\activate
pip install -r requirements.txt
cp .env.example .env
python -m uvicorn main:app --reload
```

API: `http://localhost:8000`
Docs: `http://localhost:8000/docs`

#### Local HTTPS (optional)
If you want HTTPS locally, generate a self-signed certificate and set:

```
SSL_CERTFILE=path/to/localhost-cert.pem
SSL_KEYFILE=path/to/localhost-key.pem
```

Example (OpenSSL):

```bash
mkdir certs
openssl req -x509 -nodes -days 365 -newkey rsa:2048 \
  -keyout certs/localhost-key.pem \
  -out certs/localhost-cert.pem \
  -subj "/CN=localhost"
```

Then run `.\dev.ps1` or `backend\start.ps1`. Your browser will show a self-signed cert warning.

### Frontend admin

```bash
cd frontend-admin
npm install
npm run dev
```

Admin: `http://localhost:5173`

## Key endpoints
See `/docs` for the full OpenAPI reference. Common endpoints include:
- `POST /api/v1/chat/` chat (RAG + product carousel + guardrails)
- `POST /api/v1/import/knowledge` import KB file (`.csv`)
- `GET /api/v1/import/knowledge/uploads` list KB upload history
- `POST /api/v1/import/products` import products CSV
- `GET /api/v1/import/products/uploads` list product upload history
- `GET /api/v1/import/template/products` download product CSV header template
- `GET /api/v1/import/template/knowledge` download KB CSV header template

## Currency (canonical USD + conversion)
- Products are stored in `BASE_CURRENCY` (default `USD`).
- Convert display currency using `CURRENCY_RATES_JSON` where rates mean: `1 USD = X units`.
- Manual SQL migrations: see `backend/sql/migrations/` for current scripts.

## Product tuning
The only active product tuning knob is `PRODUCT_DISTANCE_THRESHOLD` (controls how strict vector product matching is in chat).

## AI Implementation Notes
- The current AI priority is implementation logic, not multi-tenant or cross-platform architecture.
- The current target is a tool-first, read-only assistant over local data.
- Avoid adding generic platform abstractions unless a second real platform exists.
- For execution guidance, use `docs/ai/agent-implementation-plan.md`.

## Tests
Unit/service tests live in `backend/tests/` (see `backend/pyproject.toml` pytest config).
Legacy ad-hoc verification scripts that used to live in root `tests/` were removed during cleanup.

```bash
cd backend
pytest -q
```

## Backend quality checks
```bash
cd backend
python scripts/check_legacy_imports.py
python scripts/check_repo_hygiene.py
ruff check app/services
pytest tests -q
```

## Logging
- `backend/backend.log` (app logger, created when running from `backend/`)
- `backend/logs/debug.log` (NDJSON debug events used by RAG/product routing)

## Scripts (manual tooling)
`backend/scripts/` is a developer/maintenance toolbox. These scripts are not part of the backend runtime startup path.

Common examples:
- Legacy import guardrail: `backend/scripts/check_legacy_imports.py`
- Debug/verification: `backend/scripts/debug_retrieval.py`, `backend/scripts/verify_chat.py`, `backend/scripts/verify_search.py`
- Maintenance/backfill: `backend/scripts/rebuild_product_search_text.py`, `backend/scripts/maintenance/cleanup_stale_knowledge.py`

## Generated folders (safe to delete, never commit)
These are local runtime/IDE/test artifacts. They are gitignored and can be removed any time:
- `backend/__pycache__/`, `backend/.tmp_pyc/`
- `backend/pytest-cache-files-*/`, `.pytest_cache/`
- `backend/uploads/`, `backend/logs/`

## Database migrations (Alembic)
Rules of thumb:
- Do not delete or rename files in `backend/alembic/versions` once created.
- If you need to undo a schema change, create a new migration that reverses it.
- Always commit migration files to GitHub with the code changes that depend on them.
- Never commit secrets like `.env` (keep them local).

Recommended workflow:
1) Make model changes
2) `alembic revision --autogenerate -m "..."` (from `backend/`)
3) Review the migration file for correctness
4) Commit code + migration together
5) Deploy and run `alembic upgrade head`

Safety checks (CI or pre-commit):
- `alembic heads`
- `alembic history --verbose`

## ngrok (tunnel backend + frontend)
This repo uses a single public ngrok URL pointing at the Vite dev server (port `5173`).
Vite proxies `/api/*` to the local FastAPI backend (port `8000`).

1) Ensure the repo root `.env` contains `NGROK_AUTHTOKEN=...` (do not commit it).

2) Start everything:

```powershell
.\dev.ps1 -Ngrok
```

3) Print the public URL(s):

```powershell
.\infra\ngrok\check-ngrok.ps1
```

Notes:
- `infra/ngrok/start-ngrok.ps1` generates `infra/ngrok/ngrok.local.yml` at runtime (gitignored) to avoid committing the authtoken.
- If `ngrok` is not on your PATH, set `NGROK_EXE` in the repo root `.env` (example: `NGROK_EXE=C:\Tools\ngrok\ngrok.exe`).
