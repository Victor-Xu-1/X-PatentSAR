import { expect, test } from '@playwright/test';

for (const width of [390, 800, 1672]) {
  test(`preview-first structure detail and raw chemistry at ${width}px`, async ({ page }) => {
    const source = process.env.PATENTSAR_E2E_SOURCE_PROJECT_ID;
    expect(source).toBeTruthy();
    const writes: string[] = [];
    await page.route('**/api/v1/**', async (route) => {
      if (route.request().method() !== 'GET') {
        writes.push(route.request().url());
        await route.abort();
      } else await route.continue();
    });
    await page.setViewportSize({ width, height: width === 390 ? 844 : 1060 });
    await page.goto('/#/projects/' + source);
    const row = page.locator('.results-table tbody tr').first();
    await expect(row).toBeVisible();
    const trigger = row.locator('.frozen-compound button');
    await trigger.click();
    const dialog = page.getByRole('dialog', { name: /^Structure details/ });
    await expect(dialog).toBeVisible();
    await expect
      .poll(() =>
        dialog
          .locator('img')
          .evaluateAll(
            (images) =>
              images.length > 0 &&
              images.every(
                (image) =>
                  (image as HTMLImageElement).complete &&
                  (image as HTMLImageElement).naturalWidth > 0,
              ),
          ),
      )
      .toBe(true);
    const smiles = dialog.getByLabel('Current SMILES', { exact: true });
    await expect(smiles).toBeHidden();
    const raw = await smiles.inputValue();
    const urls = await dialog
      .locator('img')
      .evaluateAll((images) => images.map((image) => image.getAttribute('src')));
    await dialog.screenshot({ path: test.info().outputPath(`details-default-${width}.png`) });
    await dialog
      .locator('summary')
      .filter({ hasText: /^Current SMILES$/ })
      .click();
    await expect(smiles).toBeVisible();
    await expect(smiles).toHaveValue(raw);
    await page
      .getByRole('combobox', { name: 'Interface language', exact: true })
      .selectOption('zh-CN');
    await expect(page.getByLabel('当前 SMILES', { exact: true })).toHaveValue(raw);
    await page.getByRole('combobox', { name: '界面语言', exact: true }).selectOption('en');
    expect(
      await dialog
        .locator('img')
        .evaluateAll((images) => images.map((image) => image.getAttribute('src'))),
    ).toEqual(urls);
    expect(await dialog.evaluate((el) => el.scrollWidth <= el.clientWidth + 1)).toBe(true);
    await page.keyboard.press('Escape');
    await expect(trigger).toBeFocused();
    expect(writes).toEqual([]);
  });
}

test('drawing read failure keeps localized UI feedback singular and saving blocked', async ({
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
  await expect(alert).toHaveText(
    'Cannot connect to the API. Check the service address and reload.',
  );
  await expect(alert).toHaveCount(1);
  await expect(dialog.getByRole('button', { name: 'Save correction', exact: true })).toBeDisabled();
  await expect(page.frameLocator('dialog.correction-dialog iframe').getByRole('alert')).toHaveCount(
    0,
  );
  await dialog.getByRole('button', { name: 'Cancel', exact: true }).click();
  expect(writes).toEqual([]);
});
