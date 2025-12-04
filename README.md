# GenAI Document Management System

A document management system with AI-powered vector search using FastAPI, React, PostgreSQL (pgvector), and Supabase Storage.

## 🎯 Features

- ✅ **Document Upload** - Upload PDF, DOCX, TXT, CSV files
- ✅ **Vector Search** - AI-powered semantic search using OpenAI embeddings
- ✅ **Supabase Storage** - Secure file storage with CDN
- ✅ **Admin Dashboard** - React-based UI for document management
- ✅ **Background Processing** - Async text extraction and embedding generation
- ✅ **RESTful API** - FastAPI with automatic OpenAPI documentation

## 📁 Project Structure

```
Project_WebChat/
├── backend/                # FastAPI backend
│   ├── app/
│   │   ├── api/           # API routes
│   │   ├── core/          # Config, security, logging
│   │   ├── models/        # SQLAlchemy models
│   │   ├── schemas/       # Pydantic schemas
│   │   ├── services/      # Business logic
│   │   └── utils/         # Utilities (file parsers, storage)
│   ├── requirements.txt
│   └── .env.example
├── frontend-admin/         # React admin dashboard
│   ├── src/
│   │   ├── api/          # API client
│   │   ├── components/   # React components
│   │   ├── routes/       # Pages
│   │   └── styles/       # Tailwind CSS
│   └── package.json
└── README.md
```

## 🚀 Quick Start

### Prerequisites

- **Python 3.12+**
- **Node.js 22+**
- **PostgreSQL 16+** with pgvector extension
- **Supabase Account** (free tier works)
- **OpenAI API Key**

### 1. Clone Repository

```bash
git clone <repo-url>
cd Project_WebChat
```

### 2. Backend Setup

#### Install Dependencies

```bash
cd backend
python -m venv venv

# Windows
.\venv\Scripts\activate

# Linux/Mac
source venv/bin/activate

pip install -r requirements.txt
```

#### Configure Environment

```bash
cp .env.example .env
```

Edit `.env` with your credentials:

```env
# Database (Supabase PostgreSQL)
DATABASE_URL=postgresql+asyncpg://user:password@host:5432/database

# OpenAI
OPENAI_API_KEY=sk-...

# Supabase Storage
SUPABASE_URL=https://your-project.supabase.co
SUPABASE_KEY=your-anon-key
SUPABASE_SERVICE_KEY=your-service-role-key
SUPABASE_BUCKET=documents

# Security
JWT_SECRET=your-secret-key-here
```

#### Setup Database

1. Create PostgreSQL database (or use Supabase)
2. Enable pgvector extension:
   ```sql
   CREATE EXTENSION IF NOT EXISTS vector;
   ```
3. Run the database setup script:
   ```bash
   python recreate_db.py
   ```

#### Setup Supabase Storage

1. Go to [Supabase Dashboard](https://app.supabase.com)
2. Create a new bucket named `documents` (private)
3. Add storage policies (see `docs/supabase_setup.md`)

#### Start Backend

```bash
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

Backend runs at: **http://localhost:8000**
API Docs: **http://localhost:8000/docs**

### 3. Frontend Setup

```bash
cd frontend-admin
npm install
npm run dev
```

Admin dashboard runs at: **http://localhost:5173**

## 📚 API Endpoints

### Health Check
- `GET /health` - Health check endpoint

### Documents
- `POST /api/v1/documents/upload` - Upload document
- `GET /api/v1/documents/` - List all documents
- `GET /api/v1/documents/{id}` - Get document by ID
- `DELETE /api/v1/documents/{id}` - Delete document

## 🛠️ Tech Stack

### Backend
- **Framework**: FastAPI
- **Database**: PostgreSQL with pgvector
- **Storage**: Supabase Storage
- **AI/ML**: OpenAI (embeddings, chat)
- **ORM**: SQLAlchemy (async)
- **File Processing**: pdfplumber, python-docx, PyPDF2

### Frontend
- **Framework**: React 18 + TypeScript
- **Build Tool**: Vite
- **Styling**: Tailwind CSS
- **State Management**: Zustand
- **HTTP Client**: Axios
- **Routing**: React Router v6

## 📖 Documentation

- [Implementation Plan](docs/implementation_plan.md) - Document CRUD implementation
- [Supabase Setup](docs/supabase_setup.md) - Storage configuration guide
- [Project Status](docs/project_status.md) - Current features and roadmap

## 🔧 Development

### Backend Development

```bash
cd backend

# Install dependencies
pip install -r requirements.txt

# Run with auto-reload
uvicorn app.main:app --reload

# Run tests (when available)
pytest
```

### Frontend Development

```bash
cd frontend-admin

# Install dependencies
npm install

# Run dev server
npm run dev

# Build for production
npm run build

# Preview production build
npm run preview
```

## 🗄️ Database Schema

### Tables
- **documents** - Document metadata
- **embeddings** - Vector embeddings for RAG
- **chat_sessions** - Chat conversation history
- **messages** - Individual chat messages

## 🔐 Security

- JWT-based authentication (currently disabled)
- Supabase Storage with signed URLs
- Environment-based configuration
- CORS enabled for frontend

## 📝 Environment Variables

See `.env.example` for all required environment variables.

**Required:**
- `DATABASE_URL` - PostgreSQL connection string
- `OPENAI_API_KEY` - OpenAI API key
- `SUPABASE_URL` - Supabase project URL
- `SUPABASE_KEY` - Supabase anon key
- `SUPABASE_SERVICE_KEY` - Supabase service role key

## 🚧 Roadmap

- [x] Document upload and storage
- [x] Vector embeddings generation
- [x] Supabase Storage integration
- [ ] Document download endpoint
- [ ] Document update endpoint
- [ ] Chat interface with RAG
- [ ] Magento integration
- [ ] User authentication

## 🤝 Contributing

1. Fork the repository
2. Create a feature branch
3. Commit your changes
4. Push to the branch
5. Open a Pull Request

## 📄 License

MIT License

## 🙋 Support

For issues and questions, please open a GitHub issue.

---

**Built with ❤️ using FastAPI, React, and Supabase**
