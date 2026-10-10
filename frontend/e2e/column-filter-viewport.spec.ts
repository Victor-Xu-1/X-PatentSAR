import { expect, test } from '@playwright/test';

// Long unsearched values on the same read-only native fixture. No submit/save/run.
for (const [width, height] of [
  [390, 600],
  [390, 844],
  [800, 600],
  [1672, 600],
]) {
  test(`bounded filter value painting and pointer targets at ${width}x${height}`, async ({
    page,
  }) => {
    const source = process.env.PATENTSAR_E2E_SOURCE_PROJECT_ID;
    expect(source).toBeTruthy();
    const writes: string[] = [],
      errors: string[] = [];
    page.on('pageerror', (error) => errors.push(error.message));
    await page.route('**/api/v1/**', (route) => {
      if (route.request().method() === 'GET') return route.continue();
      writes.push(route.request().url());
      return route.abort();
    });
    await page.setViewportSize({ width: width!, height: height! });
    await page.goto('/#/projects/' + source);
    const table = page.locator('.results-table');
    await expect(table.locator('tbody tr').first()).toBeVisible();
    const raw = (await table.locator('tbody .frozen-compound button').first().innerText()).trim();
    const opener = table.locator('th[data-column="compound"]').getByRole('button');
    await opener.click();
    const menu = page.locator('dialog.column-menu');
    await expect(menu.getByLabel('Select all filter values', { exact: true })).toBeEnabled();
    await menu.getByLabel('Select all filter values', { exact: true }).uncheck();
    await menu.getByLabel('Filter value ' + raw, { exact: true }).check();
    const list = menu.locator('.column-value-choices');
    // Opening near the viewport bottom must retain a useful value working area,
    // rather than reserving less height than the panel's own preferred maximum.
    expect((await list.boundingBox())!.height).toBeGreaterThanOrEqual(144);
    const frame = (await menu.boundingBox())!;
    expect(frame.y).toBeGreaterThanOrEqual(8);
    expect(frame.y + frame.height).toBeLessThanOrEqual(height! - 8 + 1);
    const escaped = await list.evaluate((node) => {
      const box = node.getBoundingClientRect();
      return [...node.querySelectorAll('input[type="checkbox"]')]
        .filter((input) => {
          const bounds = input.getBoundingClientRect();
          const x = bounds.x + bounds.width / 2,
            y = bounds.y + bounds.height / 2;
          return (
            (x < box.left || x > box.right || y < box.top || y > box.bottom) &&
            node.contains(document.elementFromPoint(x, y))
          );
        })
        .map((input) => input.getAttribute('aria-label'));
    });
    expect(escaped, 'No value may paint/hit-test over the filter actions').toEqual([]);
    await menu.screenshot({ path: test.info().outputPath(`long-filter-${width}-${height}.png`) });
    if (width === 390 && height === 844) {
      const language = page.getByRole('combobox', { name: 'Interface language', exact: true });
      await language.click();
      await language.selectOption('zh-CN');
      await expect(menu.getByLabel('筛选值 ' + raw, { exact: true })).toBeChecked();
      expect((await list.boundingBox())!.height).toBeGreaterThanOrEqual(144);
      await menu.screenshot({ path: test.info().outputPath('long-filter-390-844-zh.png') });
    }
    await page.keyboard.press('Escape');
    await expect(opener).toBeFocused();
    expect(writes).toEqual([]);
    expect(errors).toEqual([]);
  });
}
