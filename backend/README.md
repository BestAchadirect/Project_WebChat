# AchaDirect Backend

Backend services for the AchaDirect AI chat experience with RAG and Magento product search.

## Features
- JWT-based authentication
- Vector similarity search with pgvector
- Magento 2 product search integration
- OpenAI LLM integration
- Chat orchestration (knowledge answers + product recommendations)

## Prerequisites
- Python 3.9+
- PostgreSQL with pgvector extension
- OpenAI API key

## Setup

### Install dependencies
```bash
pip install -r requirements.txt
```

### Configure environment
```bash
cp .env.example .env
```

Update `.env` with your configuration:
```
DATABASE_URL=postgresql+asyncpg://user:password@localhost/dbname
OPENAI_API_KEY=sk-...
SECRET_KEY=your-secret-key-here
```

### Run database migrations
```bash
cd backend
alembic upgrade head
```

If you are connecting to an existing database that already matches the models, you can baseline it with:
```bash
cd backend
alembic stamp head
```

Note: Alembic imports the SQLAlchemy models. Ensure Python dependencies are installed (including `pgvector`) before running Alembic commands.
Legacy schema scripts are kept in `backend/scripts/legacy` for reference only.

## Run the server
```bash
cd backend
uvicorn main:app --reload --host 0.0.0.0 --port 8000
```

API documentation: `http://localhost:8000/docs`

### Local HTTPS (optional)
If you want HTTPS locally, generate a self-signed certificate and set:

```
SSL_CERTFILE=path/to/localhost-cert.pem
SSL_KEYFILE=path/to/localhost-key.pem
```

Then start the server (e.g. `backend\start.ps1` or `uvicorn ...`). The browser will show a self-signed cert warning.

## Project layout (backend)
```
main.py                        # FastAPI app entrypoint
alembic/                       # Alembic migrations
app/
  config.py                    # Settings
  dependencies.py              # DI dependencies
  models/                      # SQLAlchemy models
  schemas/                     # Pydantic schemas
  api/
    deps.py                    # Auth dependencies
    routes/                    # API routes
  services/                    # Business logic
  core/                        # Security, logging, exceptions
  utils/                       # Utilities
```

## Testing
Automated backend tests live in `backend/tests/` and do not require the API server to be running.
Scripts in `backend/scripts/` are manual verification/maintenance tools.

## Quality checks
```bash
cd backend
python scripts/check_legacy_imports.py
python scripts/check_repo_hygiene.py
ruff check app/services
pytest tests -q
```

## Klevu Full Sync Worker (Queue Mode)
To avoid in-process stalls, enable queue mode and run a dedicated worker:

```bash
# .env
KLEVU_SYNC_USE_EXTERNAL_WORKER=true
KLEVU_SYNC_WORKER_POLL_SECONDS=5
```

Start worker:

```bash
cd backend
python scripts/sync_klevu_products.py --worker
```

Run a single claim-and-exit cycle (useful for cron/probes):

```bash
cd backend
python scripts/sync_klevu_products.py --worker --once
```

## Scripts and Tests Registry (Agent Editing Guide)
This section is the canonical map for `backend/scripts/` and `backend/tests/`.

Status meaning:
- `ACTIVE`: tracked file that should be extended when scope matches.
- `DRAFT`: local file not tracked yet; review before keeping.
- `GENERATED/INACTIVE`: cache artifact; safe to delete.

As of March 6, 2026:

### `backend/scripts/` (manual tooling, not API startup path)
| Status | File | Purpose |
|---|---|---|
| ACTIVE | `scripts/backfill_product_categories.py` | Backfill product category mappings. |
| ACTIVE | `scripts/backfill_product_embeddings.py` | Backfill missing product embeddings. |
| ACTIVE | `scripts/backfill_product_embedding_model.py` | Backfill embedding model metadata for products. |
| ACTIVE | `scripts/backfill_product_projection.py` | Backfill product projection data. |
| ACTIVE | `scripts/check_db.py` | Quick database connectivity/state check. |
| ACTIVE | `scripts/check_legacy_imports.py` | Guardrail for banned legacy import paths. |
| ACTIVE | `scripts/check_product_groups.py` | Validate product grouping consistency. |
| ACTIVE | `scripts/check_qa_logs.py` | Inspect QA logs for issues. |
| ACTIVE | `scripts/check_repo_hygiene.py` | Repository hygiene checks. |
| ACTIVE | `scripts/cleanup_verify_artifacts.py` | Clean local artifacts from verify runs. |
| ACTIVE | `scripts/count_chunks.py` | Count knowledge chunks/statistics. |
| ACTIVE | `scripts/debug_retrieval.py` | Debug retrieval results for a query. |
| ACTIVE | `scripts/inspect_enum.py` | Inspect enum values/state in DB. |
| ACTIVE | `scripts/kb_coverage.py` | Report knowledge base coverage metrics. |
| ACTIVE | `scripts/profile_chat_latency.py` | Profile chat latency. |
| ACTIVE | `scripts/rebuild_product_search_text.py` | Rebuild searchable product text/index field. |
| ACTIVE | `scripts/sync_klevu_products.py` | Run Klevu product sync flow (manual/full/queued worker). |
| ACTIVE | `scripts/verify_chat.py` | Manual chat verification utility. |
| ACTIVE | `scripts/verify_knowledge_v2.py` | Manual knowledge verification utility. |
| ACTIVE | `scripts/verify_search.py` | Manual product/search verification utility. |
| ACTIVE | `scripts/maintenance/cleanup_stale_knowledge.py` | Remove stale knowledge artifacts. |
| DRAFT | `scripts/backfill_category_facet_eav.py` | Backfill EAV facet/category data. |
| DRAFT | `scripts/check_category_facet_parity.py` | Compare category facet parity. |
| DRAFT | `scripts/fix_klevu_object_id_overlap.py` | Repair overlapping Klevu object IDs. |
| DRAFT | `scripts/migrate_simple_sku_object_id_to_klevu_id.py` | Migrate object IDs to Klevu ID format. |
| DRAFT | `scripts/seed_facet_definitions.py` | Seed facet definition records. |
| GENERATED/INACTIVE | `scripts/__pycache__/` and `*.pyc` | Python runtime cache; safe to delete. |

### `backend/tests/` (pytest suite)
| Status | File | Purpose |
|---|---|---|
| ACTIVE | `tests/conftest.py` | Shared pytest bootstrap/config. |
| ACTIVE | `tests/test_agent_orchestrator.py` | Agent orchestration flow tests. |
| ACTIVE | `tests/test_agent_tools.py` | Agent tools behavior/contracts tests. |
| ACTIVE | `tests/test_category_taxonomy_service.py` | Category taxonomy service tests. |
| ACTIVE | `tests/test_chat_component_builders.py` | Chat component builder tests. |
| ACTIVE | `tests/test_chat_component_cache.py` | Chat component cache tests. |
| ACTIVE | `tests/test_chat_component_field_resolver.py` | Chat field resolver tests. |
| ACTIVE | `tests/test_chat_component_planner.py` | Chat planner tests. |
| ACTIVE | `tests/test_chat_component_registry.py` | Chat component registry tests. |
| ACTIVE | `tests/test_chat_commerce_intents.py` | Compare/recommend intent runtime tests. |
| ACTIVE | `tests/test_chat_component_service_mode.py` | Chat service mode tests. |
| ACTIVE | `tests/test_chat_conversation_state.py` | Conversation state helper/runtime/persistence tests. |
| ACTIVE | `tests/test_chat_detail_helpers.py` | Chat detail helper tests. |
| ACTIVE | `tests/test_chat_detail_mode.py` | Chat detail mode tests. |
| ACTIVE | `tests/test_chat_follow_up_policy.py` | Follow-up policy tests. |
| ACTIVE | `tests/test_chat_hybrid_routing.py` | Hybrid routing tests. |
| ACTIVE | `tests/test_chat_performance_guards.py` | Performance guardrail tests. |
| ACTIVE | `tests/test_chat_runtime_metrics.py` | Runtime metrics tests. |
| ACTIVE | `tests/test_chat_sku_precheck_policy.py` | SKU precheck policy tests. |
| ACTIVE | `tests/test_chat_sku_precheck_runtime.py` | SKU precheck runtime tests. |
| ACTIVE | `tests/test_data_import_helper_compat.py` | Import helper compatibility tests. |
| ACTIVE | `tests/test_klevu_sync_service.py` | Klevu sync service tests. |
| ACTIVE | `tests/test_product_embedding_model_filter.py` | Product embedding model filter tests. |
| ACTIVE | `tests/test_product_projection_service.py` | Product projection service tests. |
| ACTIVE | `tests/test_response_consistency.py` | Response consistency tests. |
| ACTIVE | `tests/test_service_adapters.py` | Service adapter compatibility tests. |
| DRAFT | `tests/test_attributes_service_facets.py` | Attribute/facet service tests. |
| DRAFT | `tests/test_products_filter_modes.py` | Product filter mode tests. |
| GENERATED/INACTIVE | `tests/__pycache__/` and `*.pyc` | Pytest/Python cache; safe to delete. |

### Agent Rules To Prevent File Sprawl
- Always modify an existing script/test first when domain matches.
- Create a new file only for a genuinely new domain with no suitable existing file.
- If a new file is created, update this registry in the same change.
- Delete stale one-off scripts/tests after migration is complete.
- Never commit generated caches (`__pycache__/`, `*.pyc`).

## Additional Docs
- Docs index: `../docs/README.md`
- Task system architecture: `../docs/architecture/task-system.md`
- Services redesign: `../docs/architecture/services-redesign.md`
- Database troubleshooting runbook: `../docs/runbooks/database-troubleshooting.md`
- Services deprecation runbook: `../docs/runbooks/services-deprecation.md`

## License
MIT
