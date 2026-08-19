import react from '@vitejs/plugin-react';
import { fileURLToPath } from 'node:url';
import { defineConfig } from 'vitest/config';

export default defineConfig({
  plugins: [react()],
  resolve: {
    alias: { '@': fileURLToPath(new URL('./src', import.meta.url)) },
  },
  test: {
    environment: 'jsdom',
    globals: true,
    setupFiles: ['./src/test/setup.ts'],
    include: ['src/**/*.test.{ts,tsx}'],
    // The card suites render a full page — table, form and modals — into jsdom,
    // and the heaviest of them sit just under vitest's 5 s default. On a cold
    // module graph they cross it and the run fails for a reason that has
    // nothing to do with the component under test.
    testTimeout: 20_000,
    hookTimeout: 20_000,
  },
});
