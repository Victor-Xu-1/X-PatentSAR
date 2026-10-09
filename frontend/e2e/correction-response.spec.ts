import { expect, test } from '@playwright/test';

test('committed correction with a lost server response is recovered by reading, not replaying', async ({
  page,
}) => {
  test.skip(
    process.env.PATENTSAR_E2E_HISTORY_MUTATIONS !== 'synthetic-isolated-state',
    'Uses only the explicitly marked fresh controller-owned synthetic fixture',
  );
  const source = process.env.PATENTSAR_E2E_SOURCE_PROJECT_ID;
  expect(source).toBeTruthy();
  let puts = 0;
  await page.route('**/api/v1/**/correction', async (route) => {
    if (route.request().method() === 'PUT') {
      puts++;
      const committed = await route.fetch();
      expect(committed.status()).toBe(200);
      await route.fulfill({ status: 503, contentType: 'application/json', body: '{}' });
    } else await route.continue();
  });
  await page.goto('/#/projects/' + source);
  const row = page.locator('.results-table tbody tr').first();
  await row.waitFor();
  const compound = await row.getAttribute('data-compound');
  expect(compound).toBeTruthy();
  const endpoint = `/api/v1/projects/${source}/structures/${encodeURIComponent(compound!)}/correction`;
  const original = await (await page.request.get(endpoint)).json();
  await row.getByRole('button', { name: /^Correct / }).click();
  const dialog = page.getByRole('dialog', { name: /^Correction/ });
  const save = dialog.getByRole('button', { name: 'Save correction', exact: true });
  await expect(save).toBeEnabled({ timeout: 30000 });
  const value = dialog.locator('.correction-values');
  await value.locator('input').first().fill('31');
  await save.click();
  const check = dialog.getByRole('button', {
    name: 'Check saved state and retain draft',
    exact: true,
  });
  await expect(check).toBeVisible();
  await expect(save).toBeDisabled();
  await expect(dialog.getByRole('alert')).toContainText('write result is unknown');
  await expect(dialog.locator('.conflict')).toHaveCount(0);
  expect(puts).toBe(1);
  await dialog.screenshot({ path: test.info().outputPath('uncertain-save-retained.png') });
  await check.click();
  await expect(dialog).toHaveCount(0);
  const recovered = await (await page.request.get(endpoint)).json();
  expect(recovered.revision).toBe(original.revision + 1);
  expect(recovered.values.activities[0].value).toBe('31');
  expect(puts).toBe(1);
});
