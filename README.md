# Project WebChat (GenAI SaaS)

FastAPI + PostgreSQL (pgvector) backend with a React admin dashboard.

Supports:
- Knowledge base import (CSV/DOCX) → chunking → embeddings → RAG chat answers
- Product import (CSV) → product embeddings → product carousel in chat
- Chat routing with guardrails: `smalltalk`, `general_chat`, `product`, `knowledge`, `mixed`, `clarify`, `fallback_general`

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
