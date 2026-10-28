import { defineConfig } from 'vite';

export default defineConfig({
  root: '.',
  publicDir: 'public',
  server: {
    port: 5173,
    proxy: {
      '/api': {
        target: 'http://localhost:8787',
        changeOrigin: true,
      },
      '/models': {
        target: 'http://localhost:8787',
        changeOrigin: true,
      },
    },
  },
  worker: {
    format: 'es',
  },
  build: {
    outDir: 'dist',
    target: 'esnext',
  },
});
