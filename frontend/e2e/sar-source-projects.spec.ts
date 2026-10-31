import { expect, test } from '@playwright/test';

// GET-only controlled presentation faults on an installed isolated backend.
// No private patent, extraction, snapshot, model or SAR job is submitted here.
for (const width of [390, 1672]) {
  test(`same-named SAR sources remain distinguishable and read-only at ${width}px`, async ({
    page,
  }, info) => {
    const origin = new URL(process.env.PATENTSAR_E2E_BASE_URL!);
    expect(['127.0.0.1', 'localhost', '[::1]']).toContain(origin.hostname);
    expect(Number(origin.port)).toBeGreaterThanOrEqual(18766);
    expect(Number(origin.port)).toBeLessThanOrEqual(18866);
    expect(process.env.PATENTSAR_E2E_RUN_JOBS).toBe('0');
    const writes: string[] = [],
      errors: string[] = [];
    let secondId = '',
      literalTitle = '';
    page.on('pageerror', (error) => errors.push(error.message));
    await page.route('**/api/v1/**', async (route) => {
      const request = route.request();
      if (request.method() !== 'GET') {
        writes.push(new URL(request.url()).pathname);
        return route.abort();
      }
      if (new URL(request.url()).pathname === '/api/v1/projects') {
        const response = await route.fetch();
        const data = await response.json();
        expect(data.items.length).toBeGreaterThan(0);
        const source = data.items[0];
        secondId = source.id === 'f'.repeat(32) ? 'e'.repeat(32) : 'f'.repeat(32);
        literalTitle = source.title;
        // Duplicate-name/timestamp UI input only, not a scientific acceptance claim.
        data.items = [source, { ...source, id: secondId }];
        return route.fulfill({ response, json: data });
      }
      return route.continue();
    });
    await page.setViewportSize({ width, height: width === 390 ? 844 : 1060 });
    await page.goto('/#/sar');
    const select = page.getByRole('combobox', { name: 'Source project', exact: true });
    await expect(select).toBeEnabled();
    await expect(select.locator('option')).toHaveCount(3);
    const labels = await select.locator('option').allTextContents();
    expect(labels[1]).toContain(literalTitle);
    expect(labels[2]).toContain(literalTitle);
    expect(labels[1]).not.toBe(labels[2]);
    expect(labels[1]).not.toContain(secondId);
    await select.selectOption(secondId);
    await page.getByText('Name (optional)', { exact: true }).click();
    await page.getByLabel('Dataset title', { exact: true }).fill('Original draft 007B');
    await page
      .getByRole('combobox', { name: 'Interface language', exact: true })
      .selectOption('zh-CN');
    await expect(page.getByRole('combobox', { name: '来源项目', exact: true })).toHaveValue(
      secondId,
    );
    await expect(page.getByRole('textbox', { name: '数据集名称', exact: true })).toHaveValue(
      'Original draft 007B',
    );
    expect(
      await page
        .getByRole('combobox', { name: '来源项目', exact: true })
        .locator('option')
        .allTextContents(),
    ).toEqual(
      expect.arrayContaining([
        expect.stringContaining('来源 1'),
        expect.stringContaining('来源 2'),
      ]),
    );
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth + 1)).toBe(
      true,
    );
    await page.screenshot({
      path: info.outputPath('same-named-sources-zh.png'),
      animations: 'disabled',
    });
    await page.getByRole('combobox', { name: '界面语言', exact: true }).selectOption('en');
    await expect(page.getByRole('combobox', { name: 'Source project', exact: true })).toHaveValue(
      secondId,
    );
    await expect(page.getByRole('textbox', { name: 'Dataset title', exact: true })).toHaveValue(
      'Original draft 007B',
    );
    expect(errors).toEqual([]);
    expect(writes).toEqual([]);
  });
}
