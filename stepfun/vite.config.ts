import { defineConfig } from 'vite';

const API_TARGET = process.env.SEEKB_KB_API || 'http://127.0.0.1:8787';

export default defineConfig({
  server: {
    port: 5173,
    proxy: {
      '/api': { target: API_TARGET, changeOrigin: true },
      '/models': { target: API_TARGET, changeOrigin: true },
    },
  },
  worker: { format: 'es' },
  build: {
    target: 'es2022',
    sourcemap: false,
  },
});
