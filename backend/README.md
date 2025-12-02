# GenAI SaaS Backend

Multi-tenant SaaS backend for GenAI chatbot with RAG and Magento integration.

## Features

- 🔐 JWT-based authentication
- 🏢 Multi-tenant architecture
- 📄 Document upload and processing (PDF, DOCX, CSV, TXT)
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
alembic upgrade head
```

### Running the Server

```bash
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

API documentation will be available at: http://localhost:8000/docs

## API Endpoints

### Authentication
- `POST /api/auth/login` - Login and get JWT token
- `POST /api/auth/register` - Register new user

### Tenants
- `POST /api/tenants` - Create tenant
- `GET /api/tenants/{id}` - Get tenant details
- `PUT /api/tenants/{id}` - Update tenant (Magento config)

### Documents
- `POST /api/documents/upload` - Upload document for processing
- `GET /api/documents/{id}` - Get document status
- `GET /api/documents` - List all documents

### Chat
- `POST /api/chat` - Send chat message

### Health
- `GET /health` - Health check

## Architecture

```
app/
├── main.py              # FastAPI app
├── config.py            # Settings
├── dependencies.py      # DI dependencies
├── models/              # SQLAlchemy models
├── schemas/             # Pydantic schemas
├── api/
│   ├── deps.py          # Auth dependencies
│   └── routes/          # API routes
├── services/            # Business logic
│   ├── llm_service.py
│   ├── rag_service.py
│   ├── magento_service.py
│   ├── chat_service.py
│   ├── document_service.py
│   └── tenant_service.py
├── core/                # Security, logging, exceptions
└── utils/               # Utilities
```

## License

MIT
