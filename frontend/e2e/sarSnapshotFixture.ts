import { expect, type Page } from '@playwright/test';
import { randomUUID } from 'node:crypto';

/** Existing isolated source adapter only: no extraction or scientific analysis. */
export async function syntheticSnapshot(page: Page) {
  const origin = new URL(process.env.PATENTSAR_E2E_BASE_URL!);
  expect(['127.0.0.1', 'localhost', '[::1]']).toContain(origin.hostname);
  expect(Number(origin.port)).toBeGreaterThanOrEqual(18766);
  expect(Number(origin.port)).toBeLessThanOrEqual(18866);
  const project = process.env.PATENTSAR_E2E_SOURCE_PROJECT_ID;
  expect(project).toMatch(/^[a-f0-9]{32}$/);
  const initialized = page.waitForResponse(
    (response) =>
      response.request().method() === 'GET' &&
      new URL(response.url()).pathname === '/api/v1/sar/datasets' &&
      response.ok(),
  );
  await page.goto('/#/sar');
  await initialized;
  const session = await page.request.get('/api/v1/session');
  expect(session.ok()).toBe(true);
  const created = await page.request.post('/api/v1/sar/datasets/project', {
    headers: { Origin: origin.origin, 'X-CSRF-Token': (await session.json()).csrf_token },
    data: { project_id: project, request_id: randomUUID().replaceAll('-', '') },
  });
  expect(created.status()).toBe(201);
  const dataset = await created.json();
  expect(dataset.row_count).toBe(30);
  expect(dataset.eligible_count).toBeGreaterThan(0);
  // Full reload reflects API fixture preparation without inventing a UI cache invalidation.
  await page.goto('/?controlled-snapshot=' + dataset.id + '#/sar?dataset=' + dataset.id);
  await expect(
    page.getByRole('combobox', { name: 'SAR datasets', exact: true }).locator('option:checked'),
  ).toHaveText(dataset.title);
  return dataset;
}
