import { expect, test } from '@playwright/test';

// Real installed components, controller-owned synthetic source state. Opening
// correction previews is read-only: never save, run extraction or call models.
for (const width of [390, 800, 1672]) {
  test(`table, source preview and Ketcher draft craft at ${width}px`, async ({ page }) => {
    const source = process.env.PATENTSAR_E2E_SOURCE_PROJECT_ID;
    expect(source).toBeTruthy();
    const errors: string[] = [],
      writes: string[] = [];
    page.on('pageerror', (error) => errors.push(error.message));
    await page.route('**/api/v1/**', async (route) => {
      // The local chemistry endpoint canonicalizes MDL without saving data.
      // It uses POST for the bounded structure body; it is not a correction.
      const chemistryRead =
        route.request().method() === 'POST' &&
        new URL(route.request().url()).pathname === '/api/v1/chemistry/structure';
      if (route.request().method() !== 'GET' && !chemistryRead) {
        writes.push(route.request().url());
        await route.abort();
      } else await route.continue();
    });
    await page.setViewportSize({ width, height: width === 390 ? 844 : 1060 });
    await page.goto('/#/projects/' + source);
    const table = page.locator('.results-table');
    const row = table.locator('tbody tr').first();
    await expect(row).toBeVisible();
    const identity = row.locator('.frozen-compound button');
    await identity.click();
    const details = page.getByRole('dialog', { name: /^Structure details/ });
    await expect(details).toBeVisible();
    await expect
      .poll(() =>
        details
          .getByRole('img')
          .first()
          .evaluate((el) => (el as HTMLImageElement).naturalWidth),
      )
      .toBeGreaterThan(0);
    expect(await details.evaluate((el) => el.scrollWidth <= el.clientWidth + 1)).toBe(true);
    await details.screenshot({ path: test.info().outputPath(`structure-details-${width}.png`) });
    await page.keyboard.press('Escape');
    await expect(identity).toBeFocused();

    const menuTrigger = table.locator('th[data-column="compound"]').getByRole('button');
    await menuTrigger.click();
    const menu = page.getByRole('dialog', { name: 'Original ID column options', exact: true });
    await expect(menu.getByLabel('Select all filter values', { exact: true })).toBeEnabled();
    await expect(menu.getByRole('button', { name: 'Ascending', exact: true })).toBeVisible();
    await expect(menu.getByRole('button', { name: 'Descending', exact: true })).toBeVisible();
    await menu.getByLabel('Find filter values', { exact: true }).fill('Compound 1');
    await expect(menu.getByLabel('Filter value Compound 1', { exact: true })).toBeVisible();
    expect(await menu.evaluate((el) => el.scrollWidth <= el.clientWidth + 1)).toBe(true);
    await menu.screenshot({ path: test.info().outputPath(`column-filter-${width}.png`) });
    await page.keyboard.press('Escape');
    await expect(menuTrigger).toBeFocused();

    await page.getByRole('button', { name: 'Show columns', exact: true }).click();
    const chooser = page.getByRole('dialog');
    await chooser.getByLabel('Show column MW', { exact: true }).uncheck();
    await expect(table.locator('th[data-column="property:molecular_weight"]')).toHaveCount(0);
    await chooser.getByLabel('Show column MW', { exact: true }).check();
    await chooser.screenshot({ path: test.info().outputPath(`column-visibility-${width}.png`) });
    await page.keyboard.press('Escape');

    const resize = table.getByRole('slider', { name: 'Resize Original ID column', exact: true });
    const before = Number(await resize.getAttribute('aria-valuenow'));
    await resize.focus();
    await resize.press('ArrowRight');
    await expect(resize).toHaveAttribute('aria-valuenow', String(before + 8));
    await row.getByRole('button', { name: /^Correct / }).click();
    const correction = page.getByRole('dialog', { name: /^Correction/ });
    await expect(
      correction.getByRole('button', { name: 'Save correction', exact: true }),
    ).toBeEnabled({ timeout: 30000 });
    const frame = page.frameLocator('iframe[title="Ketcher structure drawing and preview"]');
    await expect(frame.getByRole('application')).toBeVisible();
    for (const metric of ['MW', 'LogP', 'TPSA', 'HBD', 'HBA', 'LogS'])
      await expect(correction.getByLabel(`Correct ${metric}`, { exact: true })).toBeVisible();
    expect(await correction.evaluate((el) => el.scrollWidth <= el.clientWidth + 1)).toBe(true);
    await correction.screenshot({ path: test.info().outputPath(`correction-${width}.png`) });
    await correction.getByRole('button', { name: 'Cancel', exact: true }).click();
    await expect(correction).toHaveCount(0);
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth + 1)).toBe(
      true,
    );
    expect(errors).toEqual([]);
    expect(writes).toEqual([]);
  });
}

test('drawing transport failure is localized once, keeps saving blocked and never saves a correction', async ({
  page,
}) => {
  const source = process.env.PATENTSAR_E2E_SOURCE_PROJECT_ID;
  expect(source).toBeTruthy();
  const writes: string[] = [];
  await page.route('**/api/v1/**', async (route) => {
    if (new URL(route.request().url()).pathname === '/api/v1/chemistry/structure')
      await route.abort();
    else if (route.request().method() !== 'GET') {
      writes.push(route.request().url());
      await route.abort();
    } else await route.continue();
  });
  await page.goto('/#/projects/' + source);
  await page
    .locator('.results-table tbody tr')
    .first()
    .getByRole('button', { name: /^Correct / })
    .click();
  const dialog = page.getByRole('dialog', { name: /^Correction/ });
  const alert = dialog.getByRole('alert');
  await expect(alert).toContainText('Connection interrupted');
  await expect(alert).toHaveCount(1);
  await expect(dialog.getByRole('button', { name: 'Save correction', exact: true })).toBeDisabled();
  const frame = page.frameLocator('iframe[title="Ketcher structure drawing and preview"]');
  await expect(frame.getByRole('alert')).toHaveCount(0);
  await dialog.screenshot({ path: test.info().outputPath('drawing-transport-error.png') });
  await dialog.getByRole('button', { name: 'Cancel', exact: true }).click();
  expect(writes).toEqual([]);
});
