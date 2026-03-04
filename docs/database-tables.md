# Database Table Catalog

Last updated: 2026-03-04

This document explains the purpose of each application table in the `public` schema.
It is intended as a practical reference for onboarding, operations, and future schema changes.

## Scope

- In scope: app-owned tables in `public`.
- Out of scope: Supabase system schemas (`auth`, `storage`, `realtime`, `vault`) and extension views.

## Retention Notes

- "Current: indefinite" means there is no automatic purge in code/migrations today.
- "Suggested" values are operational guidance you can adopt as policy.

## Table Catalog

| Table | Domain Owner | Purpose | Key Relations | Primary Touchpoints | Retention Guidance |
| --- | --- | --- | --- | --- | --- |
| `alembic_version` | Platform | Tracks current migration revision for Alembic. | None | `backend/alembic/*` | Keep indefinitely (metadata). |
| `app_user` | Chat, Tickets | Stores end-user identity used by chat and support flows. | Referenced by `conversation.user_id`, `ticket.user_id`. | `app/services/chat/service.py`, `app/services/tickets/service.py` | Current: indefinite. Suggested: keep while account/ticket history is active. |
| `conversation` | Chat | Represents a chat session, including state and activity timestamps. | `user_id -> app_user.id`; parent of `message`. | `app/services/chat/service.py`, `app/services/chat/persistence.py`, `app/api/routes/analytics.py` | Current: indefinite. Suggested: 12-24 months for analytics, or archive. |
| `message` | Chat | Stores each chat message (role, content, optional product payload, token usage). | `conversation_id -> conversation.id`. | `app/services/chat/persistence.py`, `app/services/chat/components/pipeline.py`, `app/api/routes/analytics.py` | Current: indefinite. Suggested: 12-24 months, then archive/redact. |
| `chat_setting` | Chat Admin | Stores chat widget/admin display configuration. Typically singleton row. | None | `app/api/routes/chat_setting.py` | Keep indefinitely (config). |
| `banner` | Admin Content | Stores storefront/dashboard banner records and ordering. | None | `app/api/routes/banner.py` | Keep active rows indefinitely; soft cleanup for old banners as needed. |
| `ticket` | Tickets | Stores support tickets, statuses, images, AI summary, and admin replies. | `user_id -> app_user.id`. | `app/services/tickets/service.py`, `app/api/routes/tickets.py` | Current: indefinite. Suggested: 24 months or per support policy. |
| `tasks` | Tasks, Imports | Tracks background/long-running task execution status and progress. | None | `app/services/tasks/service.py`, `app/api/routes/tasks.py`, import workflows | Current: indefinite. Suggested: purge completed/failed older than 30-90 days. |
| `qa_logs` | Chat, QA Dashboard | Stores Q/A outcomes, sources, status, feedback, and token usage for quality monitoring. | None | `app/services/chat/persistence.py`, `app/api/routes/training.py`, `app/api/routes/analytics.py` | Current: indefinite. Suggested: 6-18 months depending on reporting needs. |
| `semantic_cache` | Chat | Stores semantic response cache entries keyed by embedding similarity and locale/currency. | None | `app/services/semantic_cache_service.py`, chat runtime | Current: bounded logically by `expires_at`; physical rows persist until explicit cleanup. Suggested: periodic delete of expired rows. |
| `knowledge_uploads` | Imports, Knowledge | Tracks knowledge import upload sessions and status/errors. | Parent of `knowledge_articles` via `upload_session_id`. | `app/services/imports/service.py`, `app/api/routes/data_import.py` | Current: indefinite. Suggested: 6-12 months for auditability. |
| `knowledge_articles` | Knowledge | Canonical knowledge document records. | `upload_session_id -> knowledge_uploads.id`; parent of versions/chunks/embeddings. | `app/services/knowledge/pipeline.py`, `app/services/imports/service.py`, `app/api/routes/training.py` | Keep indefinitely (source content). |
| `knowledge_article_versions` | Knowledge | Version history per knowledge article. | `article_id -> knowledge_articles.id`. | `app/services/imports/service.py`, maintenance scripts | Keep indefinitely for audit/version traceability. |
| `knowledge_chunks` | Knowledge | Text chunks derived from article versions for retrieval. | `article_id -> knowledge_articles.id`; parent of tags and chunk-linked embeddings. | `app/services/knowledge/pipeline.py`, `app/api/routes/training.py` | Rebuildable, but usually kept indefinitely. |
| `knowledge_chunk_tags` | Knowledge | Optional chunk tags used for retrieval filtering/boosting. | `chunk_id -> knowledge_chunks.id`. | `app/services/knowledge/pipeline.py` | Keep with chunk lifecycle. |
| `knowledge_embeddings` | Knowledge | Vector embeddings for article/chunk retrieval in RAG. | `article_id -> knowledge_articles.id`, optional `chunk_id -> knowledge_chunks.id`. | `app/services/knowledge/pipeline.py`, `app/services/imports/service.py`, `app/api/routes/training.py` | Rebuildable; retain until re-embedding strategy replaces them. |
| `products` | Catalog | Core product catalog data (SKU, pricing, stock, attributes, grouping, search text). | `group_id -> product_groups.id`, optional `product_upload_id -> product_uploads.id`. | `app/services/catalog/*`, `app/services/chat/*`, `app/api/routes/products.py`, import services | Keep indefinitely (primary business data). |
| `product_groups` | Catalog | Master/variant grouping for products (master code family). | Parent of `products`. | `app/services/imports/service.py`, `app/services/imports/klevu_sync_service.py`, `app/api/routes/products.py` | Keep indefinitely with catalog. |
| `attribute_definitions` | Catalog | Dictionary of normalized attribute keys/types used by EAV. | Parent of `product_attribute_values`. | `app/services/catalog/attributes_service.py`, chat/catalog query services | Keep indefinitely; low churn dictionary. |
| `product_attribute_values` | Catalog | EAV values per product and attribute. | `product_id -> products.id`, `attribute_id -> attribute_definitions.id`. | `app/services/catalog/attributes_service.py`, `app/services/catalog/product_search.py`, chat services | Keep with product lifecycle; rebuildable from source import if needed. |
| `product_embeddings` | Catalog | Vector embeddings for semantic product search. | `product_id -> products.id`. | `app/services/catalog/product_search.py`, `app/services/imports/service.py`, `app/services/imports/klevu_sync_service.py` | Rebuildable; retain until re-embedding. |
| `product_search_projection` | Catalog | Denormalized/normalized projection optimized for filtered search queries. | `product_id -> products.id` (PK/FK). | `app/services/catalog/projection_service.py`, `app/services/catalog/product_search.py`, chat pipeline | Derived table; safe to rebuild from products + attributes. |
| `product_uploads` | Imports | Tracks product CSV upload sessions (status, progress, error log). | Referenced by `products.product_upload_id`; linked from `product_changes.upload_id`. | `app/services/imports/service.py`, `app/api/routes/data_import.py` | Current: indefinite. Suggested: 6-12 months for operational audit. |
| `product_changes` | Imports, Catalog | Per-product diff/audit records generated during imports/sync runs. | `product_id -> products.id`, optional `upload_id -> product_uploads.id`. | `app/services/imports/service.py`, `app/services/imports/klevu_sync_service.py`, product delete flows | Current: indefinite. Suggested: 3-12 months, depending on audit requirement. |
| `klevu_sync_runs` | Imports | Run-level execution log for Klevu sync jobs (status, counters, offsets, config snapshot). | Parent of `klevu_sync_failures`. | `app/services/imports/klevu_sync_service.py`, sync scripts/routes | Current: indefinite. Suggested: 3-6 months for operational diagnostics. |
| `klevu_sync_failures` | Imports | Per-record failure diagnostics for Klevu sync runs. | `run_id -> klevu_sync_runs.id`. | `app/services/imports/klevu_sync_service.py` | Current: indefinite. Suggested: 1-3 months, or keep with run retention. |

## Quick Dependency View

```text
app_user
  -> conversation
      -> message
  -> ticket

knowledge_uploads
  -> knowledge_articles
      -> knowledge_article_versions
      -> knowledge_chunks
          -> knowledge_chunk_tags
          -> knowledge_embeddings
      -> knowledge_embeddings

product_groups
  -> products
      -> product_attribute_values -> attribute_definitions
      -> product_embeddings
      -> product_search_projection
      -> product_changes
product_uploads
  -> products
  -> product_changes

klevu_sync_runs
  -> klevu_sync_failures
```

## Operational Notes

- Derived/rebuildable tables: `product_embeddings`, `product_search_projection`, `knowledge_embeddings`, and often `knowledge_chunks`.
- Audit/ops tables that can grow quickly: `qa_logs`, `tasks`, `product_changes`, `klevu_sync_runs`, `klevu_sync_failures`.
- If you adopt retention jobs, implement deletes in batches and monitor table bloat/vacuum behavior.
