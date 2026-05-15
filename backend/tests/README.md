# Backend Tests

This backend test suite is split into focused layers so fast deterministic checks stay separate from slower workflow and grounded-data coverage.

- `unit`: deterministic function and policy tests.
- `integration`: internal workflow orchestration and component pipeline behavior.
- `api`: FastAPI request and response contracts.
- `regression`: protection against known bugs and previously captured chat failures.
- `evaluation`: scenario-based chatbot behavior quality checks.
- `db_grounded`: seeded catalog and knowledge truth checks that require a test PostgreSQL database.

Fast local tests:

```powershell
cd backend
pytest tests/unit tests/integration/chat -q
```

Full backend tests:

```powershell
cd backend
python scripts/check_legacy_imports.py
python scripts/check_repo_hygiene.py
ruff check app/services
pytest tests -q
```

Evaluation tests:

```powershell
cd backend
pytest tests/evaluation -q
```

DB-grounded tests:

```powershell
cd backend
TEST_DATABASE_URL=postgresql://... pytest -m db_grounded -q
```
