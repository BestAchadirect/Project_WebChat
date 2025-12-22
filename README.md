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

