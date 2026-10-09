import { test, expect } from '@playwright/test';
// Presentation only: no provider, installer, extraction, deletion or correction writes.
for (const width of [390, 800, 1672])
  test(`expert visual pages and key dialogs at ${width}px`, async ({ page }) => {
    const errors: string[] = [],
      writes: string[] = [];
    page.on('pageerror', (error) => errors.push(error.message));
    await page.route('**/api/v1/**', async (route) => {
      if (route.request().method() !== 'GET') {
        writes.push(route.request().url());
        await route.abort();
      } else await route.continue();
    });
    await page.setViewportSize({ width, height: width === 390 ? 844 : 1060 });
    for (const [route, heading, ready] of [
      ['new-task', 'Upload patent PDF', '.upload-drop'],
      ['projects', 'Recent files', '.recent-files,.recent-files-page .empty'],
      ['jobs', 'Tasks', '.job-history,.jobs-page .empty'],
      ['settings', 'Environment', '.environment-overview'],
    ]) {
      await page.goto('/#/' + route);
      await expect(page.getByRole('heading', { name: heading!, exact: true })).toBeVisible();
      await expect(page.locator(ready!).first()).toBeVisible();
      expect(
        await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth + 1),
      ).toBe(true);
      await page.screenshot({ path: test.info().outputPath(`${route}-${width}.png`) });
    }
    await page.getByRole('button', { name: 'Storage locations', exact: true }).click();
    await expect(page.getByRole('dialog')).toBeVisible();
    expect(
      await page.getByRole('dialog').evaluate((el) => el.scrollWidth <= el.clientWidth + 1),
    ).toBe(true);
    await page.screenshot({ path: test.info().outputPath(`storage-${width}.png`) });
    await page.keyboard.press('Escape');
    await page
      .getByRole('region', { name: 'LLM API', exact: true })
      .getByRole('button', { name: 'Configure', exact: true })
      .click();
    await expect(page.getByRole('dialog', { name: 'LLM API settings', exact: true })).toBeVisible();
    expect(
      await page.getByRole('dialog').evaluate((el) => el.scrollWidth <= el.clientWidth + 1),
    ).toBe(true);
    await page.screenshot({ path: test.info().outputPath(`llm-${width}.png`) });
    await page.keyboard.press('Escape');
    const source = process.env.PATENTSAR_E2E_SOURCE_PROJECT_ID;
    expect(source).toBeTruthy();
    await page.goto('/#/projects/' + source);
    await expect(page.locator('.results-table tbody tr').first()).toBeVisible();
    const image = page.locator('.results-table tbody img').first();
    await expect
      .poll(() => image.evaluate((el) => (el as HTMLImageElement).naturalWidth))
      .toBeGreaterThan(0);
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth + 1)).toBe(
      true,
    );
    await page.screenshot({ path: test.info().outputPath(`workspace-${width}.png`) });
    const labels = await page.locator('.workflow-group > span:last-child').allTextContents();
    // This read-only imported fixture has no invented job history. Current and
    // legacy recorded chains can have different consecutive grouping counts.
    expect(
      labels.every((label) => ['Parse', 'Structure', 'Activity', 'Validate'].includes(label)),
    ).toBe(true);
    if (!labels.length)
      await expect(page.getByLabel('Stage groups', { exact: true })).toHaveCount(0);
    const clipped = await page
      .locator('.workflow-group > span:last-child')
      .evaluateAll((items) => items.some((item) => item.scrollWidth > item.clientWidth + 1));
    expect(clipped).toBe(false);
    await page.getByRole('button', { name: 'Evidence', exact: true }).click();
    await expect(page.getByRole('heading', { name: 'Evidence', exact: true })).toBeVisible();
    await page.screenshot({ path: test.info().outputPath(`summary-${width}.png`) });
    expect(errors).toEqual([]);
    expect(writes).toEqual([]);
  });
