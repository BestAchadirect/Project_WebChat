# Admin Dashboard

React + TypeScript admin dashboard for the GenAI SaaS platform.

## Features

- 🔐 Authentication with JWT
- 📄 Document management (upload PDF/DOC/CSV)
- ⚙️ Magento integration settings
- 📊 Analytics and chat logs
- 🎨 Premium UI with Tailwind CSS

## Getting Started

### Installation

```bash
npm install
```

### Development

```bash
npm run dev
```

### Build

```bash
npm run build
```

### Chat Widget Build

```bash
npm run build:widget
```

Builds `widget.js` and `widget.css` into `backend/app/static` for the embedded chat widget.

### Environment Variables

Create a `.env` file based on `.env.example`:

```
VITE_API_BASE_URL=http://localhost:8000/api/v1
VITE_WIDGET_ORIGIN=http://localhost:8000
```

## Tech Stack

- **React 18** - UI framework
- **TypeScript** - Type safety
- **Vite** - Build tool
- **React Router v6** - Routing
- **Tailwind CSS** - Styling
- **Axios** - HTTP client
- **Zustand** - State management
- **React Hook Form** - Form handling
- **Zod** - Schema validation
