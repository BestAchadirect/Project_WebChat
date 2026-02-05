# AchaDirect Admin Dashboard

React + TypeScript admin dashboard for the AchaDirect AI chat experience.

## Features
- Authentication with JWT
- Document management (upload CSV)
- Magento integration settings
- Analytics and chat logs
- Tailwind-based UI

## Getting started

### Install
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

### Chat widget build
```bash
npm run build:widget
```

Builds `widget.js` and `widget.css` into `backend/app/static` for the embedded chat widget.

## Environment variables
Create a `.env` file based on `.env.example`:

```
VITE_API_BASE_URL=http://localhost:8000/api/v1
VITE_WIDGET_ORIGIN=http://localhost:8000
```

## Tech stack
- React 18
- TypeScript
- Vite
- React Router v6
- Tailwind CSS
- Axios
- Zustand
- React Hook Form
- Zod
