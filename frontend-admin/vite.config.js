var __assign = (this && this.__assign) || function () {
    __assign = Object.assign || function(t) {
        for (var s, i = 1, n = arguments.length; i < n; i++) {
            s = arguments[i];
            for (var p in s) if (Object.prototype.hasOwnProperty.call(s, p))
                t[p] = s[p];
        }
        return t;
    };
    return __assign.apply(this, arguments);
};
import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';
import { fileURLToPath } from 'node:url';
// https://vitejs.dev/config/
export default defineConfig({
    plugins: [react()],
    resolve: {
        alias: {
            '@': fileURLToPath(new URL('./src', import.meta.url)),
        },
    },
    server: (function () {
        var hmrHost = process.env.VITE_DEV_HMR_HOST;
        var backendTarget = process.env.VITE_DEV_BACKEND_URL || 'http://127.0.0.1:8000';
        var attachForwardedHeaders = function (proxy) {
            proxy.on('proxyReq', function (proxyReq, req, _res) {
                var forwardedHost = req.headers['x-forwarded-host'] || req.headers.host;
                if (forwardedHost) {
                    var hostValue = Array.isArray(forwardedHost) ? forwardedHost[0] : forwardedHost;
                    proxyReq.setHeader('x-forwarded-host', hostValue);
                }
                var forwardedProto = req.headers['x-forwarded-proto'];
                if (forwardedProto) {
                    var protoValue = Array.isArray(forwardedProto) ? forwardedProto[0] : forwardedProto;
                    proxyReq.setHeader('x-forwarded-proto', protoValue);
                }
                console.log('Sending Request to the Target:', req.method, req.url);
            });
            proxy.on('error', function (err, _req, _res) {
                console.log('proxy error', err);
            });
            proxy.on('proxyRes', function (proxyRes, req, _res) {
                console.log('Received Response from the Target:', proxyRes.statusCode, req.url);
            });
        };
        var backendProxy = {
            target: backendTarget,
            changeOrigin: true,
            secure: false,
            configure: function (proxy) { return attachForwardedHeaders(proxy); },
        };
        return __assign({ host: '0.0.0.0', port: 5173, strictPort: true, cors: true, 
            // Allow ngrok subdomains (dev only). Safer than `true` and fixes Vite host-blocking (403).
            allowedHosts: ['.ngrok-free.dev'], proxy: {
                '/api': backendProxy,
                '/uploads': backendProxy,
            } }, (hmrHost
            ? {
                hmr: {
                    host: hmrHost,
                    clientPort: 443,
                    protocol: 'wss',
                },
            }
            : {}));
    })(),
});
