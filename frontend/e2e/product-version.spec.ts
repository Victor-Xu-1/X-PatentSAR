import { expect, test } from '@playwright/test';
import packageMetadata from '../package.json' with { type: 'json' };
import type { Health } from '../src/api/types';

// Python CI verifies this derived npm version against the contracts.py authority.
const expectedVersion = packageMetadata.version;
const routes = [
  { path: 'new-task', heading: '上传专利 PDF' },
  { path: 'projects', heading: '最近文件' },
  { path: 'jobs', heading: '任务记录' },
  { path: 'settings', heading: '环境管理' },
];

for (const viewport of [
  { width: 1672, height: 942 },
  { width: 800, height: 900 },
  { width: 390, height: 844 },
]) {
  for (const route of routes) {
    test(`build version matches health and Header on ${route.path} at ${viewport.width}`, async ({
      page,
    }) => {
      const writes: string[] = [];
      page.on('request', (request) => {
        if (request.method() !== 'GET' && new URL(request.url()).pathname.startsWith('/api/v1/'))
          writes.push(request.url());
      });
      await page.setViewportSize(viewport);
      const healthResponse = page.waitForResponse(
        (response) =>
          response.request().method() === 'GET' &&
          new URL(response.url()).pathname === '/api/v1/health',
      );
      await page.goto(`/#/${route.path}`);
      const response = await healthResponse;
      expect(response.ok()).toBe(true);
      const health = (await response.json()) as Health;
      expect(health.product.name).toBe('X-PatentSAR');
      expect(health.product.version).toBe(expectedVersion);
      await expect(page.getByRole('heading', { name: route.heading, exact: true })).toBeVisible();
      const version = page.locator('.topbar').getByLabel('软件版本', { exact: true });
      await expect(version).toBeVisible();
      await expect(version).toHaveText(`v${expectedVersion}`);
      expect(writes).toEqual([]);
    });
  }
}
