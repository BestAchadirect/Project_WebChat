# Project WebChat (GenAI SaaS)

FastAPI + PostgreSQL (pgvector) backend with a React admin dashboard.

Supports:
- Knowledge base import (CSV) → chunking → embeddings → RAG chat answers
- Product import (CSV) → product embeddings → product carousel in chat
- Chat routing with Unified NLU: `browse_products`, `search_specific`, `knowledge_query`, `off_topic`

### New Features (Jan 2026)
- **Smart Product Search**:
  - **Exact SKU Match**: Returns 1 specific product (e.g., "Find SKU-123").
  - **Master Code / Name Match**: Returns all variants in the group (e.g., "Titanium Clicker").
  - **AI Code Detection**: Intelligently extracts codes from natural language (e.g., "Find me code ACCO.") using system prompts.
  - **Fallback**: Vector semantic search if no strict code match found.
  - **Increased Limit**: Carousel now shows up to 10 products (previously 3).
- **Interactive Banner Carousel**: Replaced static greeting with touch-friendly rotating banners.
- **Dynamic Quick Replies**:
  - **Context-Aware**: AI suggests 3-5 relevant follow-up questions (e.g., "Shipping costs?", "View Cart").
  - **Smart Fallback**: "See more [Category]" button if no specific questions generated.

## Structure

```
Project_WebChat/
  backend/                # FastAPI backend
    app/                  # DB models, schemas, services
    scripts/              # runnable test suites + debug tools
    sql/migrations/       # manual DB migration scripts (Supabase)
  frontend-admin/         # React admin UI
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

Then run `.\dev.ps1` or `backend\start.ps1`. Your browser will show a self‑signed cert warning.

### Frontend admin

```bash
cd frontend-admin
npm install
npm run dev
```

Admin: `http://localhost:5173`

## Key endpoints

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

## Test suites (API must be running)

- Product carousel: `python backend/scripts/run_product_carousel_test_suite.py --suite backend/tests/product_carousel_test.json`
- Smalltalk/general chat guardrails: `python backend/scripts/run_smalltalk_test_suite.py --suite backend/tests/smalltalk_test.json`

## Logging

- `backend/backend.log` (app logger)
- `backend/logs/debug.log` (NDJSON debug events used by RAG/product routing)

## Database migrations (Alembic)

Rules of thumb:
- **Do not delete or rename** files in `backend/alembic/versions` once created.
- If you need to undo a schema change, **create a new migration** that reverses it.
- Always commit migration files to GitHub **with** the code changes that depend on them.
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
1.  **Check Backend**: Ensure `backend` is running on port 8000.
2.  **CORS**: Check `ALLOWED_ORIGINS` in `.env`. For ngrok dev, set `ALLOWED_ORIGINS=*`.
3.  **Proxy SSL**: In `vite.config.ts`, ensure `secure: false` is set in the proxy config to allow self-signed/local certs.
4.  **Redirects (307)**: Ensure your API calls end with a slash if the backend route requires it (or verify your API routes don't enforce trailing slashes).
    - Example: Requesting `/api/v1/products` when `/api/v1/products/` is expected causes a redirect that breaks some proxies.

### `dev.ps1` Issues
- **PowerShell Execution Policy**: You may need to run `Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass`.
- **Node/IPv6**: The script forces `http://127.0.0.1:8000` for the backend URL to avoid Node.js localhost IPv6 resolution issues on Windows.
