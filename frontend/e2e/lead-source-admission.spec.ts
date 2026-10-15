import { expect, test } from '@playwright/test';
import packageMetadata from '../package.json' with { type: 'json' };

// Real backend on the existing isolated historical adapter. No route interception,
// scientific writer, extraction/model execution or fake successful source.
for (const width of [1280, 390]) {
  test(`historical sources never display automatic Lead ranks at ${width}px`, async ({
    page,
  }, testInfo) => {
    const project = process.env.PATENTSAR_E2E_SOURCE_PROJECT_ID;
    expect(project).toBeTruthy();
    const errors: string[] = [],
      writes: string[] = [];
    page.on('pageerror', (error) => errors.push(error.message));
    page.on('request', (request) => {
      if (new URL(request.url()).pathname.startsWith('/api/v1/') && request.method() !== 'GET')
        writes.push(request.method() + ' ' + new URL(request.url()).pathname);
    });
    await page.setViewportSize({ width, height: 900 });
    await page.goto('/#/projects/' + project);
    const health = await page.request.get('/api/v1/health');
    expect(health.ok()).toBe(true);
    expect((await health.json()).product.version).toBe(packageMetadata.version);
    await expect(page.getByText('v' + packageMetadata.version, { exact: true })).toBeVisible();
    const table = page.getByRole('table');
    await expect(table).toBeVisible();
    const observed = await page.request.get(`/api/v1/projects/${project}/results`);
    expect(observed.ok()).toBe(true);
    const data = await observed.json();
    expect(data.items.length).toBeGreaterThan(0);
    expect(
      data.items.every(
        (row: { lead: { status: string; rank: number | null; score: number | null } }) =>
          row.lead.status === 'unranked' && row.lead.rank === null && row.lead.score === null,
      ),
    ).toBe(true);
    const original = data.items.map(
      (row: { id: string; display_id: string; activities: unknown[] }) => ({
        id: row.id,
        display_id: row.display_id,
        activities: row.activities,
      }),
    );
    const cell = table.locator('tbody td[data-column="lead"]').first();
    await cell.scrollIntoViewIfNeeded();
    await expect(cell).toHaveText('—');
    await expect(cell).toHaveAttribute('data-lead-status', 'unranked');
    await expect(cell).toHaveAttribute('title', /Historical sources are review-only/);
    await expect(page.locator('.lead-badge')).toHaveCount(0);
    await page
      .getByRole('combobox', { name: 'Interface language', exact: true })
      .selectOption('zh-CN');
    await expect(cell).toHaveAttribute('title', /历史来源仅供复核/);
    await page.reload();
    await expect(cell).toHaveAttribute('data-lead-status', 'unranked');
    await expect(cell).toHaveAttribute('title', /历史来源仅供复核/);
    const unchanged = await page.request.get(`/api/v1/projects/${project}/results`);
    expect(
      (await unchanged.json()).items.map(
        (row: { id: string; display_id: string; activities: unknown[] }) => ({
          id: row.id,
          display_id: row.display_id,
          activities: row.activities,
        }),
      ),
    ).toEqual(original);
    expect(
      await page.evaluate(() => document.documentElement.scrollWidth - innerWidth),
    ).toBeLessThanOrEqual(2);
    expect(writes).toEqual([]);
    expect(errors).toEqual([]);
    await page.screenshot({
      path: testInfo.outputPath(`lead-source-${width}.png`),
      fullPage: true,
    });
  });
}
