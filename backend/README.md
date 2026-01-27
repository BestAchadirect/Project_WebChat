# GenAI SaaS Backend

Multi-tenant SaaS backend for GenAI chatbot with RAG and Magento integration.

## Features

- 🔐 JWT-based authentication
- 🏢 Multi-tenant architecture
- 🔍 Vector similarity search with pgvector
- 🛒 Magento 2 product search integration
- 🤖 OpenAI LLM integration
- 💬 Intelligent chat orchestration (FAQ + Product recommendations)

## Setup

### Prerequisites

- Python 3.9+
- PostgreSQL with pgvector extension
- OpenAI API key

### Installation

1. Install dependencies:
```bash
pip install -r requirements.txt
```

2. Create `.env` file:
```bash
cp .env.example .env
```

3. Update `.env` with your configuration:
```
DATABASE_URL=postgresql+asyncpg://user:password@localhost/dbname
OPENAI_API_KEY=sk-...
SECRET_KEY=your-secret-key-here
```

4. Run database migrations:
```bash
cd backend
alembic upgrade head
```
If you're connecting to an existing database that already matches the models, you can baseline it with:
```bash
cd backend
alembic stamp head
```
Note: Alembic imports the SQLAlchemy models. Ensure Python dependencies are installed
(including `pgvector`) before running Alembic commands.
Schema changes should go through Alembic; legacy schema scripts are kept in
`backend/scripts/legacy` for reference only.

### Running the Server

```bash
cd backend
uvicorn main:app --reload --host 0.0.0.0 --port 8000
```

API documentation will be available at: http://localhost:8000/docs

### Local HTTPS (optional)

If you want HTTPS locally, generate a self-signed certificate and set:

```
SSL_CERTFILE=path/to/localhost-cert.pem
SSL_KEYFILE=path/to/localhost-key.pem
```

Then start the server (e.g. `backend\start.ps1` or `uvicorn ...`). The browser will show a self‑signed cert warning.

## API Endpoints

### Authentication
- `POST /api/auth/login` - Login and get JWT token
- `POST /api/auth/register` - Register new user

### Tenants
- `POST /api/tenants` - Create tenant
- `GET /api/tenants/{id}` - Get tenant details
- `PUT /api/tenants/{id}` - Update tenant (Magento config)

### Chat
- `POST /api/chat` - Send chat message

### Health
- `GET /health` - Health check

## Architecture

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
    llm_service.py
    rag_service.py
    magento_service.py
    chat_service.py
    tenant_service.py
  core/                        # Security, logging, exceptions
  utils/                       # Utilities
```

## License

MIT
