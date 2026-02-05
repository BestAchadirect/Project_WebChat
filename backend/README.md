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
API must be running for the test runners in `backend/scripts/`.

## License
MIT
