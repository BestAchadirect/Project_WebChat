import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import { fileURLToPath } from 'node:url'

// https://vitejs.dev/config/
export default defineConfig({
    plugins: [react()],
    resolve: {
        alias: {
            '@': fileURLToPath(new URL('./src', import.meta.url)),
        },
    },
    server: (() => {
        const hmrHost = process.env.VITE_DEV_HMR_HOST
        const backendTarget = process.env.VITE_DEV_BACKEND_URL || 'http://localhost:8000'

        return {
            host: '0.0.0.0',
            port: 5173,
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
})
