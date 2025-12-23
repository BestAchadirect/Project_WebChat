import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

export default defineConfig({
  plugins: [react()],
  server: (() => {
    const hmrHost = process.env.VITE_DEV_HMR_HOST
    const backendTarget = process.env.VITE_DEV_BACKEND_URL || 'http://localhost:8000'

    return {
      host: '0.0.0.0',
      port: 5174,
      strictPort: true,
      cors: true,
      // Allow ngrok subdomains (dev only). Safer than `true` and fixes Vite host-blocking (403).
      allowedHosts: ['.ngrok-free.dev'],
      proxy: {
        '/api': {
          target: backendTarget,
          changeOrigin: true,
        },
      },
      ...(hmrHost
        ? {
            hmr: {
              host: hmrHost,
              clientPort: 443,
              protocol: 'wss',
            },
          }
        : {}),
    }
  })(),
  define: {
    'process.env.NODE_ENV': '"production"'
  },
  build: {
    outDir: 'dist',
    emptyOutDir: true,
    lib: {
      entry: 'src/embed.jsx',
      name: 'GenAIChatWidget',
      fileName: () => 'widget.js',
      formats: ['iife']
    },
    rollupOptions: {
      output: {
        assetFileNames: (assetInfo) => {
          if (assetInfo.name === 'style.css') return 'widget.css';
          return assetInfo.name;
        }
      }
    }
  }
})
