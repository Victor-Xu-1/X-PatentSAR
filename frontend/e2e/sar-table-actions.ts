import { expect, test } from '@playwright/test';
import type { Locator, Page } from '@playwright/test';

/** Existing isolated native study only; presentation/query controls never write. */
export async function checkStudyTableControls(page: Page, report: Locator, width: number) {
  const view = report.getByRole('region', { name: 'Activity table', exact: true });
  const table = view.getByRole('table');
  const options = view.getByRole('button', { name: 'Filters and sort', exact: true });
  const search = view.getByRole('searchbox', { name: 'Search identifiers or SMILES', exact: true });
  await expect(options).toHaveAttribute('aria-expanded', 'false');
  await expect(view.getByLabel('Row scope', { exact: true })).not.toBeVisible();
  await expect(view.locator('.sar-hint')).toHaveCount(0);
  expect(
    await table.locator('th,td').evaluateAll((cells) =>
      cells.every((cell) => {
        const style = getComputedStyle(cell);
        return style.textAlign === 'center' && style.verticalAlign === 'middle';
      }),
    ),
  ).toBe(true);
  if (width === 1672)
    expect(
      await view
        .locator('.sar-study-table-toolbar')
        .evaluate((el) => el.getBoundingClientRect().height),
    ).toBeLessThan(50);

  await options.click();
  await view.getByLabel('Sort (all study rows)', { exact: true }).selectOption('label');
  await view.getByLabel('Sort direction', { exact: true }).selectOption('desc');
  await expect(table.getByRole('rowheader').first()).toHaveText('Example 16');
  await search.fill('Example 2');
  await expect(table.locator('tbody tr')).toHaveCount(1);
  await expect(table.getByRole('rowheader')).toHaveText('Example 2');
  await options.click();
  await expect(view.getByLabel('Sort direction', { exact: true })).not.toBeVisible();
  await expect(options).toHaveText(/1$/);

  const columns = view.getByRole('button', { name: 'Column settings', exact: true });
  await columns.click();
  const chooser = page.getByRole('dialog', { name: 'Column settings', exact: true });
  await chooser.getByRole('checkbox', { name: 'Show column MW', exact: true }).uncheck();
  await page.keyboard.press('Escape');
  await expect(columns).toBeFocused();
  await expect(table.getByRole('columnheader', { name: 'MW', exact: true })).toHaveCount(0);

  await options.click();
  await expect(view.getByLabel('Sort direction', { exact: true })).toHaveValue('desc');
  await view.getByRole('button', { name: 'Reset filters and sort', exact: true }).click();
  await expect(search).toHaveValue('Example 2');
  await expect(table.getByRole('columnheader', { name: 'MW', exact: true })).toHaveCount(0);
  await options.click();
  await expect(options).not.toHaveAttribute('data-active');
  await columns.click();
  await chooser.getByRole('checkbox', { name: 'Show column MW', exact: true }).check();
  await page.keyboard.press('Escape');
  await expect(table.getByRole('columnheader', { name: 'MW', exact: true })).toBeVisible();
  await search.fill('No source match 原文');
  await expect(view.getByText('No matching rows', { exact: true })).toBeVisible();
  await search.fill('');
  await expect(table.locator('tbody tr')).toHaveCount(16);
  await expect(table.getByRole('rowheader').first()).toHaveText('Example 1');
  await page.screenshot({ path: test.info().outputPath(`table-tools-${width}.png`) });
}
