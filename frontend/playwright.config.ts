import { defineConfig, devices } from '@playwright/test';
const baseURL = process.env.PATENTSAR_E2E_BASE_URL ?? 'http://127.0.0.1:8765';
const origin = new URL(baseURL);
if (!['127.0.0.1', 'localhost', '[::1]'].includes(origin.hostname))
  throw new Error('E2E must target an explicitly owned loopback service');

export default defineConfig({
  testDir: './e2e',
  fullyParallel: false,
  workers: 1,
  retries: 0,
  timeout: 90_000,
  expect: { timeout: 15_000 },
  outputDir: process.env.PATENTSAR_E2E_OUTPUT_DIR ?? '/srv/wsl/tmp/x-patentsar-ui-e2e',
  reporter: [['list']],
  use: {
    baseURL,
    trace: 'retain-on-failure',
    screenshot: 'only-on-failure',
    actionTimeout: 15_000,
  },
  projects: [
    {
      name: 'chromium',
      use: { ...devices['Desktop Chrome'], viewport: { width: 1672, height: 942 } },
    },
  ],
  // The controller starts the real backend. This config never starts or stops a server.
});
