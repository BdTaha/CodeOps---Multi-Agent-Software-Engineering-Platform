import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';

export default defineConfig({
  base: '/ui/',
  plugins: [react()],
  server: { proxy: { '/tasks': { target: 'http://127.0.0.1:8765', changeOrigin: true,
    configure: proxy => proxy.on('proxyReq', (outgoing, incoming) => {
      // Translate only this app's origin; preserve other origins for rejection.
      if (incoming.headers.origin === 'http://127.0.0.1:5173' || incoming.headers.origin === 'http://localhost:5173') outgoing.setHeader('origin', 'http://127.0.0.1:8765');
    }) },
    '/projects': { target: 'http://127.0.0.1:8765', changeOrigin: true, configure: proxy => proxy.on('proxyReq', (outgoing, incoming) => { if (incoming.headers.origin === 'http://127.0.0.1:5173' || incoming.headers.origin === 'http://localhost:5173') outgoing.setHeader('origin', 'http://127.0.0.1:8765'); }) }, '/system': 'http://127.0.0.1:8765', '/evaluation': 'http://127.0.0.1:8765', '/health': 'http://127.0.0.1:8765' } },
});
