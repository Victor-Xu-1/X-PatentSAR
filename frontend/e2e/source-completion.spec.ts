import { expect, test } from '@playwright/test';

// Explicit isolated saved-observation adapters; not extraction/chemical evidence.
// The browser reads the real installed projection and never submits a model job.
for (const width of [390, 1672]) {
  test(`all-original source projection at ${width}px`, async ({ page }) => {
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
    for (const [kind, status] of [
      ['PENDING', 'unavailable'],
      ['COMPLETE', 'valid'],
      ['CONFLICTING', 'invalid'],
      ['HISTORICAL', 'unavailable'],
    ] as const) {
      const project = process.env[`PATENTSAR_E2E_COMPLETION_${kind}_PROJECT`];
      expect(project).toBeTruthy();
      await page.goto('/#/projects/' + project);
      const table = page.locator('.results-table');
      await expect(table.locator('tbody tr')).toHaveCount(2);
      const row = table.locator('tbody tr').first();
      await expect(row.locator('.frozen-compound')).toContainText('Compound 1');
      if (status !== 'valid') await expect(row.locator('.prediction-value')).toHaveCount(0);
      const opener = row.locator('.frozen-compound button');
      await opener.click();
      const dialog = page.getByRole('dialog', {
        name: 'Structure details · Compound 1',
        exact: true,
      });
      await expect(dialog).toBeVisible();
      await expect(
        dialog.getByRole('img', { name: 'Original structure crop for Compound 1', exact: true }),
      ).toBeVisible();
      await dialog
        .getByText('Other original sources for this identifier (1)', { exact: true })
        .click();
      await expect(
        dialog.getByRole('link', { name: 'Original page 1', exact: true }),
      ).toBeVisible();
      if (kind === 'HISTORICAL') {
        await expect(
          dialog.getByText('Historical source references; not validated under current rules.', {
            exact: true,
          }),
        ).toBeVisible();
        await expect(
          dialog.getByText(
            'These repeated sources are confirmed by identifier and spatial evidence, not treated as another unassociated compound.',
            { exact: true },
          ),
        ).toHaveCount(0);
      }
      if (status === 'valid') {
        await dialog.locator('.crop-smiles summary').click();
        await expect(dialog.getByLabel('Current SMILES', { exact: true })).toHaveValue('CCO');
      } else await expect(dialog.getByLabel('Current SMILES', { exact: true })).toHaveCount(0);
      await dialog.getByText('Original extraction evidence / validation', { exact: true }).click();
      await expect(dialog.locator(`.recognition-${status}`)).toBeVisible();
      expect(await dialog.evaluate((el) => el.scrollWidth <= el.clientWidth + 1)).toBe(true);
      await dialog.screenshot({ path: test.info().outputPath(`source-${kind}-${width}.png`) });
      await page.keyboard.press('Escape');
      await expect(opener).toBeFocused();
      await page.reload();
      await expect(table.locator('tbody tr')).toHaveCount(2);
    }
    expect(errors).toEqual([]);
    expect(writes).toEqual([]);
  });
}
