# GenAI SaaS for Magento Merchants

A multi-tenant SaaS platform that enables Magento merchants to add AI-powered chat to their stores. The AI answers questions from uploaded documents (RAG) and recommends products from the merchant's catalog.

## Project Structure

```
saas-genai-magento/
├── backend/                # FastAPI (RAG, Magento, auth, multi-tenant)
├── frontend-admin/         # React admin dashboard (for merchants)
├── frontend-widget/        # React chat widget (embeddable script)
├── shared/                 # Shared types, OpenAPI schema
├── infra/                  # Docker, docker-compose, CI/CD
├── docs/                   # Architecture, API docs
└── .env.example
```

## Quick Start

### Prerequisites
- Python 3.12+
- Node.js 22+
- PostgreSQL 16+ with pgvector extension

### 1. Clone and Setup

```bash
git clone <repo-url>
cd Project_WebChat
cp .env.example .env
# Edit .env with your OpenAI API key and database URL
```

### 2. Backend

```bash
cd backend
python -m venv venv

# Windows
.\venv\Scripts\activate
# Linux/Mac
source venv/bin/activate

pip install -r requirements.txt
uvicorn main:app --reload
```

Backend runs at: http://localhost:8000

### 3. Frontend Admin (Merchant Dashboard)

```bash
cd frontend-admin
npm install
npm run dev
```

Admin dashboard runs at: http://localhost:5173

### 4. Frontend Widget (Embeddable Chat)

```bash
cd frontend-widget
npm install
npm run dev
```

Widget dev server runs at: http://localhost:5174

To build the embeddable widget:
```bash
npm run build
# Output: dist/widget.iife.js
```

### Using Docker Compose

```bash
cd infra
docker-compose up
```

## Documentation

- [Architecture](docs/architecture.md) - System design and data flow
- [API Contracts](docs/api-contracts.md) - API documentation (TODO)
- [Deployment](docs/deployment.md) - Deployment guide (TODO)

## Tech Stack

- **Backend**: Python, FastAPI, PostgreSQL, pgvector, OpenAI
- **Frontend**: React, Vite, Tailwind CSS
- **Infrastructure**: Docker, Docker Compose

