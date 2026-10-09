import { expect, test } from '@playwright/test';

for (const width of [390, 800, 1672]) {
  test(`recent file title, metadata and keyboard opening at ${width}px`, async ({ page }) => {
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
    await page.goto('/#/projects');
    // Wait for the app's normal session bootstrap and source-list read before
    // using the context's authenticated read-only API client.
    await expect(page.locator('.recent-file-row').first()).toBeVisible();
    const sourceId = process.env.PATENTSAR_E2E_SOURCE_PROJECT_ID;
    expect(sourceId).toBeTruthy();
    const source = await page.request.get('/api/v1/projects/' + sourceId);
    expect(source.status()).toBe(200);
    const { title, updated_at } = await source.json();
    const open = page.getByRole('button', { name: 'Open ' + title, exact: true });
    await expect(open).toBeVisible();
    await expect(open.locator('strong')).toHaveText(title);
    await expect(open.locator('time')).toHaveAttribute('datetime', updated_at);
    await expect(open).toHaveAccessibleDescription(/Original PDF not provided/);
    const layout = await open.evaluate((button) => {
      const title = button.querySelector('.recent-file-name')!;
      const row = button.closest('.recent-file-row')!;
      return {
        titleWidth: title.getBoundingClientRect().width,
        rowWidth: row.getBoundingClientRect().width,
        columns: getComputedStyle(row).gridTemplateColumns.split(' ').length,
      };
    });
    expect(layout.titleWidth / layout.rowWidth).toBeGreaterThan(width <= 1000 ? 0.6 : 0.2);
    expect(layout.columns).toBe(width <= 1000 ? 1 : 2);
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth + 1)).toBe(
      true,
    );
    await page.screenshot({
      path: test.info().outputPath(`recent-density-${width}.png`),
      fullPage: true,
    });
    await open.focus();
    await page.keyboard.press('Enter');
    await expect(page).toHaveURL(new RegExp('#/projects/' + sourceId));
    await expect(page.locator('.results-table tbody tr').first()).toBeVisible();
    expect(errors).toEqual([]);
    expect(writes).toEqual([]);
  });
}
