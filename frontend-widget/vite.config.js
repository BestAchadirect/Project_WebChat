import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

export default defineConfig({
  plugins: [react()],
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
