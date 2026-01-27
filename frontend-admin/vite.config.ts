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
        const backendTarget = process.env.VITE_DEV_BACKEND_URL || 'http://127.0.0.1:8000'

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
                    secure: false,
                    configure: (proxy, _options) => {
                        proxy.on('error', (err, _req, _res) => {
                            console.log('proxy error', err);
                        });
                        proxy.on('proxyReq', (proxyReq, req, _res) => {
                            console.log('Sending Request to the Target:', req.method, req.url);
                        });
                        proxy.on('proxyRes', (proxyRes, req, _res) => {
                            console.log('Received Response from the Target:', proxyRes.statusCode, req.url);
                        });
                    },
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
