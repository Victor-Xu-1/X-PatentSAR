import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';
import { fileURLToPath } from 'node:url';

const proxyTarget = process.env.PATENTSAR_API_PROXY_TARGET ?? 'http://127.0.0.1:8765';
const target = new URL(proxyTarget);
if (
  target.protocol !== 'http:' ||
  !['127.0.0.1', 'localhost', '[::1]'].includes(target.hostname) ||
  target.username ||
  target.password ||
  target.pathname !== '/' ||
  target.search ||
  target.hash
) {
  throw new Error('PATENTSAR_API_PROXY_TARGET must be a loopback HTTP origin');
}

export default defineConfig({
  cacheDir: process.env.PATENTSAR_FRONTEND_CACHE_DIR ?? 'node_modules/.vite',
  plugins: [react()],
  define: { global: 'globalThis' },
  resolve: {
    alias: {
      events: fileURLToPath(new URL('./node_modules/events/events.js', import.meta.url)),
      // Geometry is needed; PaperScript's runtime JS compiler is not. Preserve CSP.
      paper: fileURLToPath(new URL('./node_modules/paper/dist/paper-core.js', import.meta.url)),
    },
  },
  server: {
    port: 5173,
    strictPort: true,
    proxy: {
      '/api': {
        target: target.origin,
        changeOrigin: true,
        configure(proxy) {
          proxy.on('proxyReq', (proxyRequest, request) => {
            const origin = request.headers.origin;
            if (origin === `http://${request.headers.host}`)
              proxyRequest.setHeader('Origin', target.origin);
          });
        },
      },
    },
  },
  build: {
    outDir: 'dist',
    license: { fileName: 'THIRD_PARTY_LICENSES.md' },
    sourcemap: false,
    rolldownOptions: {
      input: { workspace: 'index.html', structureEditor: 'ketcher.html' },
    },
  },
});
