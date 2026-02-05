# Project WebChat (AchaDirect)

## Business Overview
Project WebChat is AchaDirect's AI-assisted customer chat experience that turns your knowledge base and Magento catalog into accurate, guided conversations. It helps teams answer customer questions, recommend products, and route requests to the right flow, without manual chat scripts.

### Who it is for
- AchaDirect ecommerce and support teams
- Product or operations teams that need reliable AI answers tied to real data
- Business owners who want measurable conversion from chat interactions

### Key benefits
- Faster answers with consistent tone and guardrails
- Better product discovery and recommendations
- Lower support load with automated, accurate responses
- Clear admin controls for content, routing, and analytics

### Core capabilities
- Knowledge base import (CSV) -> chunking -> embeddings -> RAG answers
- Magento product import (CSV) -> product embeddings -> product carousel in chat
- Intent routing with Unified NLU: browse_products, search_specific, knowledge_query, off_topic

### Recent improvements (January 2026)
- Smart product search
  - Exact SKU match and master code grouping
  - AI code detection from natural language
  - Semantic fallback when exact match is not found
  - Carousel limit increased to 10 products
- Interactive banner carousel for the chat greeting
- Dynamic, context-aware quick replies

## Technical Overview
FastAPI + PostgreSQL (pgvector) backend with a React admin dashboard.

## Project Structure
See `Agent.md` for the canonical directory structure and responsibilities.

Quick view:

```
Project_WebChat/
  backend/                # FastAPI backend
  frontend-admin/         # React admin UI
  shared/                 # Shared types and utilities
  docs/                   # Architecture notes and guides
  infra/                  # Infrastructure and deployment
  tests/                  # End-to-end and integration tests
```

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
python -m venv venv
.\venv\Scripts\activate
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
- `POST /api/v1/chat` chat (RAG + product carousel + guardrails)
- `POST /api/v1/import/knowledge` import KB file (`.csv` / `.docx`)
- `GET /api/v1/import/knowledge/uploads` list KB upload history
- `POST /api/v1/import/products` import products CSV
- `GET /api/v1/import/products/uploads` list product upload history
- `GET /api/v1/import/template/products` download product CSV header template
- `GET /api/v1/import/template/knowledge` download KB CSV header template

## Currency (canonical USD + conversion)
- Products are stored in `BASE_CURRENCY` (default `USD`).
- Convert display currency using `CURRENCY_RATES_JSON` where rates mean: `1 USD = X units`.
- Manual migration (Supabase SQL editor): `backend/sql/migrations/2025_12_19_products_currency_usd.sql`

## Product tuning
The only active product tuning knob is `PRODUCT_DISTANCE_THRESHOLD` (controls how strict vector product matching is in chat).

## Test suites (API must be running)
- Product carousel: `python backend/scripts/run_product_carousel_test_suite.py --suite backend/tests/product_carousel_test.json`
- Smalltalk/general chat guardrails: `python backend/scripts/run_smalltalk_test_suite.py --suite backend/tests/smalltalk_test.json`

## Logging
- `backend/backend.log` (app logger)
- `backend/logs/debug.log` (NDJSON debug events used by RAG/product routing)

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

## Troubleshooting

### `ERR_NETWORK` / Network Error (Axios)
If you see "Network Error" in the frontend (especially via ngrok):
1. Check backend: ensure `backend` is running on port 8000.
2. CORS: check `ALLOWED_ORIGINS` in `.env`. For ngrok dev, set `ALLOWED_ORIGINS=*`.
3. Proxy SSL: in `vite.config.ts`, ensure `secure: false` is set in the proxy config to allow self-signed/local certs.
4. Redirects (307): ensure your API calls end with a slash if the backend route requires it (or verify your API routes do not enforce trailing slashes).
   - Example: requesting `/api/v1/products` when `/api/v1/products/` is expected causes a redirect that breaks some proxies.

### `dev.ps1` issues
- PowerShell execution policy: you may need to run `Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass`.
- Node/IPv6: the script forces `http://127.0.0.1:8000` for the backend URL to avoid Node.js localhost IPv6 resolution issues on Windows.
