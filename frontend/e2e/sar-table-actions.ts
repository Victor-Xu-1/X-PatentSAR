import { expect, test } from '@playwright/test';
import type { Locator, Page } from '@playwright/test';

async function checkRootFooter(dialog: Locator) {
  const footer = dialog.locator(':scope > .dialog-actions');
  await expect(footer).toHaveCount(1);
  expect(await footer.getByRole('button').count()).toBeGreaterThan(0);
  expect(
    await footer.evaluate((element) => {
      const bounds = element.closest('dialog')!.getBoundingClientRect();
      return [element, ...element.querySelectorAll('button')].every((item) => {
        const box = item.getBoundingClientRect();
        return (
          box.left >= bounds.left &&
          box.right <= bounds.right &&
          box.top >= bounds.top &&
          box.bottom <= bounds.bottom
        );
      });
    }),
  ).toBe(true);
}

async function checkIdentityHeading(table: Locator) {
  const pane = table.locator('..');
  await pane.evaluate((element) => {
    element.scrollLeft = Math.min(600, element.scrollWidth - element.clientWidth);
    element.scrollTop = 100;
  });
  const geometry = await table.evaluate((element) => {
    const bounds = element.parentElement!.getBoundingClientRect();
    const heading = element.querySelector('thead th.sar-study-identifier')!.getBoundingClientRect();
    const label = element.querySelector('tbody th[scope="row"]')!.getBoundingClientRect();
    return {
      paneLeft: bounds.left,
      paneTop: bounds.top,
      headingLeft: heading.left,
      headingTop: heading.top,
      labelLeft: label.left,
    };
  });
  expect(geometry.headingLeft).toBeGreaterThanOrEqual(geometry.paneLeft - 1);
  expect(Math.abs(geometry.headingLeft - geometry.labelLeft)).toBeLessThan(1);
  expect(Math.abs(geometry.headingTop - geometry.paneTop)).toBeLessThan(2);
  await pane.evaluate((element) => {
    element.scrollLeft = 0;
    element.scrollTop = 0;
  });
}

/** Existing isolated native study only; presentation/query controls never write. */
export async function checkStudyTableControls(page: Page, report: Locator, width: number) {
  const view = report.getByRole('region', { name: 'Activity table', exact: true });
  const table = view.getByRole('table');
  const options = view.getByRole('button', { name: 'Filters and sort', exact: true });
  const search = view.getByRole('searchbox', { name: 'Search identifiers or SMILES', exact: true });
  await expect(options).toHaveAttribute('aria-expanded', 'false');
  await expect(view.getByRole('combobox', { name: 'Row scope', exact: true })).not.toBeVisible();
  await expect(view.locator('.sar-hint')).toHaveCount(0);
  expect(
    await table.locator('th,td').evaluateAll((cells) =>
      cells.every((cell) => {
        const style = getComputedStyle(cell);
        return style.textAlign === 'center' && style.verticalAlign === 'middle';
      }),
    ),
  ).toBe(true);
  await checkIdentityHeading(table);
  if (width === 1672)
    expect(
      await view
        .locator('.sar-study-table-toolbar')
        .evaluate((el) => el.getBoundingClientRect().height),
    ).toBeLessThan(50);

  await options.click();
  await view
    .getByRole('combobox', { name: 'Sort (all study rows)', exact: true })
    .selectOption('label');
  await view.getByRole('combobox', { name: 'Sort direction', exact: true }).selectOption('desc');
  await expect(table.getByRole('rowheader').first()).toHaveText('Example 16');
  await search.fill('Example 2');
  await expect(table.locator('tbody tr')).toHaveCount(1);
  await expect(table.getByRole('rowheader')).toHaveText('Example 2');
  await options.click();
  await expect(
    view.getByRole('combobox', { name: 'Sort direction', exact: true }),
  ).not.toBeVisible();
  await expect(options).toHaveText(/1$/);

  const columns = view.getByRole('button', { name: 'Column settings', exact: true });
  await columns.click();
  const chooser = page.getByRole('dialog', { name: 'Column settings', exact: true });
  await checkRootFooter(chooser);
  await chooser.getByRole('checkbox', { name: /^Show column MW · Dalton$/ }).uncheck();
  await page.keyboard.press('Escape');
  await expect(columns).toBeFocused();
  await expect(table.getByRole('columnheader', { name: 'MW', exact: true })).toHaveCount(0);

  await options.click();
  await expect(view.getByRole('combobox', { name: 'Sort direction', exact: true })).toHaveValue(
    'desc',
  );
  await view.getByRole('button', { name: 'Reset filters and sort', exact: true }).click();
  await expect(search).toHaveValue('Example 2');
  await expect(table.getByRole('columnheader', { name: 'MW', exact: true })).toHaveCount(0);
  await options.click();
  await expect(options).not.toHaveAttribute('data-active');
  await columns.click();
  await chooser.getByRole('checkbox', { name: /^Show column MW · Dalton$/ }).check();
  await page.keyboard.press('Escape');
  await expect(table.getByRole('columnheader', { name: 'MW', exact: true })).toBeVisible();
  await search.fill('No source match 原文');
  await expect(view.getByText('No matching rows', { exact: true })).toBeVisible();
  await search.fill('');
  await expect(table.locator('tbody tr')).toHaveCount(16);
  await expect(table.getByRole('rowheader').first()).toHaveText('Example 1');
  const originalID = table
    .getByRole('rowheader')
    .first()
    .getByRole('button', { name: 'Example 1', exact: true });
  await originalID.click();
  const source = page.getByRole('dialog', { name: 'Source details · Example 1', exact: true });
  await expect(source).toBeVisible();
  expect(
    await source.evaluate(
      (element) =>
        element.getBoundingClientRect().top >= 0 &&
        element.getBoundingClientRect().bottom <= innerHeight + 1,
    ),
  ).toBe(true);
  await checkRootFooter(source);
  await page.keyboard.press('Escape');
  await expect(originalID).toBeFocused();
  const firstRow = table.locator('tbody tr').first();
  const inspect = firstRow.getByRole('button', {
    name: 'Enlarge structure Example 1',
    exact: true,
  });
  await expect(inspect).toBeEnabled();
  const drawing = await firstRow.locator('.sar-study-image img').getAttribute('src');
  await inspect.click();
  const focus = page.getByRole('dialog', { name: 'Molecular preview · Example 1', exact: true });
  await expect(focus.getByRole('img', { name: 'Example 1', exact: true })).toHaveAttribute(
    'src',
    drawing!,
  );
  await page.keyboard.press('Escape');
  await expect(inspect).toBeFocused();
  await columns.click();
  const identifierChoice = chooser.getByRole('checkbox', {
    name: /^Show column Original ID(?: ·|$)/,
  });
  await identifierChoice.uncheck();
  await page.keyboard.press('Escape');
  await expect(table.locator('.sar-study-identifier')).toHaveCount(0);
  await expect(table.getByRole('rowheader')).toHaveCount(0);
  expect(
    await table
      .getByRole('columnheader', { name: 'Structure', exact: true })
      .evaluate((element) => getComputedStyle(element).left),
  ).toBe('auto');
  await columns.click();
  await identifierChoice.check();
  await page.keyboard.press('Escape');
  await expect(table.getByRole('rowheader').first()).toHaveText('Example 1');
  await checkIdentityHeading(table);
  await page.screenshot({ path: test.info().outputPath(`table-tools-${width}.png`) });
  const studyOptions = page.getByText('Study options', { exact: true });
  const history = page.getByText('Study task history', { exact: true });
  await studyOptions.click();
  await history.click();
  const remove = page.getByRole('button', { name: 'Remove SAR job', exact: true }).first();
  await remove.click();
  const confirmation = page.getByRole('dialog', { name: 'Remove SAR job', exact: true });
  await checkRootFooter(confirmation);
  await confirmation.getByRole('button', { name: 'Cancel', exact: true }).click();
  await expect(remove).toBeFocused();
  await history.click();
  await studyOptions.click();
}
