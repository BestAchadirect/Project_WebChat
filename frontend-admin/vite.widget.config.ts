import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';
import { fileURLToPath } from 'node:url';

export default defineConfig({
    plugins: [react()],
    define: {
        'process.env.NODE_ENV': '"production"',
    },
    build: {
        outDir: '../backend/app/static',
        emptyOutDir: false,
        cssCodeSplit: true,
        lib: {
            entry: fileURLToPath(new URL('./src/widget/embed.tsx', import.meta.url)),
            name: 'GenAIChatWidget',
            formats: ['iife'],
            fileName: () => 'widget.js',
        },
        rollupOptions: {
            output: {
                assetFileNames: (assetInfo) => {
                    if (assetInfo.name === 'style.css') {
                        return 'widget.css';
                    }
                    return assetInfo.name || 'widget.css';
                },
            },
        },
    },
});
