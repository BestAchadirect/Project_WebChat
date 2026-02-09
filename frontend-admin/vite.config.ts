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

        const attachForwardedHeaders = (proxy: any) => {
            proxy.on('proxyReq', (proxyReq: any, req: any, _res: any) => {
                const forwardedHost = req.headers['x-forwarded-host'] || req.headers.host
                if (forwardedHost) {
                    const hostValue = Array.isArray(forwardedHost) ? forwardedHost[0] : forwardedHost
                    proxyReq.setHeader('x-forwarded-host', hostValue)
                }
                const forwardedProto = req.headers['x-forwarded-proto']
                if (forwardedProto) {
                    const protoValue = Array.isArray(forwardedProto) ? forwardedProto[0] : forwardedProto
                    proxyReq.setHeader('x-forwarded-proto', protoValue)
                }
                console.log('Sending Request to the Target:', req.method, req.url)
            })
            proxy.on('error', (err: any, _req: any, _res: any) => {
                console.log('proxy error', err)
            })
            proxy.on('proxyRes', (proxyRes: any, req: any, _res: any) => {
                console.log('Received Response from the Target:', proxyRes.statusCode, req.url)
            })
        }

        const backendProxy = {
            target: backendTarget,
            changeOrigin: true,
            secure: false,
            configure: (proxy: any) => attachForwardedHeaders(proxy),
        }

        return {
            host: '0.0.0.0',
            port: 5173,
            strictPort: true,
            cors: true,
            // Allow ngrok subdomains (dev only). Safer than `true` and fixes Vite host-blocking (403).
            allowedHosts: ['.ngrok-free.dev'],
            proxy: {
                '/api': backendProxy,
                '/uploads': backendProxy,
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
