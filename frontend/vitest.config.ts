import { defineConfig } from 'vitest/config';
import react from '@vitejs/plugin-react';

export default defineConfig({
  cacheDir: process.env.PATENTSAR_FRONTEND_CACHE_DIR ?? 'node_modules/.vite',
  plugins: [react()],
  test: {
    environment: 'jsdom',
    setupFiles: ['./tests/setup.ts'],
    include: ['tests/**/*.test.{ts,tsx}'],
    maxWorkers: 2,
    restoreMocks: true,
    clearMocks: true,
  },
});
