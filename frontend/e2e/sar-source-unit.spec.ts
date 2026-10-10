import { expect, test, type Page, type TestInfo } from '@playwright/test';

// Real CSV parser and persisted isolated data; no saved region, study, model or
// production mutation. Raw names/IDs/values must survive locale changes.
async function importCSV(page: Page, width: number) {
  const origin = new URL(process.env.PATENTSAR_E2E_BASE_URL!);
  expect(['127.0.0.1', 'localhost', '[::1]']).toContain(origin.hostname);
  expect(Number(origin.port)).toBeGreaterThanOrEqual(18766);
  expect(Number(origin.port)).toBeLessThanOrEqual(18866);
  await page.goto('/#/sar');
  const panel = page.getByRole('region', { name: 'Import data', exact: true });
  await panel.getByRole('button', { name: 'CSV file', exact: true }).click();
  await panel.getByLabel('Choose a CSV file', { exact: true }).setInputFiles({
    name: `controlled-unit-${width}.csv`,
    mimeType: 'text/csv',
    buffer: Buffer.from(
      [
        'id,smiles,IC50 (nM),target,assay,cell_line,duration',
        'Example 1,COc1ccc(Cl)cc1,<10,T,binding,not applicable,1h',
        'I-255,CCOc1ccc(Cl)cc1,1,T,binding,not applicable,1h',
        '8B,CCOc1ccc(Br)cc1,0.1,T,binding,not applicable,1h',
        'Unresolved,,2,T,binding,not applicable,1h',
      ].join('\n'),
    ),
  });
  await panel.getByRole('button', { name: 'Preview on server', exact: true }).click();
  await expect(panel.getByRole('group', { name: 'CSV mapping', exact: true })).toBeVisible();
  await panel
    .getByRole('combobox', { name: 'Source identifier column', exact: true })
    .selectOption('id');
  await panel.getByRole('combobox', { name: 'SMILES column', exact: true }).selectOption('smiles');
  await panel.getByRole('checkbox', { name: 'IC50 (nM)', exact: true }).check();
  const saved = page.waitForResponse(
    (response) =>
      response.request().method() === 'POST' &&
      new URL(response.url()).pathname === '/api/v1/sar/datasets/csv',
  );
  await panel.getByRole('button', { name: 'Create CSV dataset', exact: true }).click();
  expect((await saved).status()).toBe(201);
  await expect(page).toHaveURL(/(?:\?|&)dataset=[a-f0-9]{32}/);
  const id = new URLSearchParams(new URL(page.url()).hash.split('?')[1]).get('dataset');
  const response = await page.request.get('/api/v1/sar/datasets/' + id);
  expect(response.ok()).toBe(true);
  const dataset = await response.json();
  expect(dataset.row_count).toBe(4);
  expect(dataset.eligible_count).toBe(3);
  expect(dataset.metrics[0].name).toBe('IC50 (nM)');
  return dataset;
}

async function capture(page: Page, info: TestInfo, name: string) {
  await page.screenshot({ path: info.outputPath(name + '.png'), animations: 'disabled' });
}

for (const width of [390, 800, 1672]) {
  test(`CSV reference units and original records stay exact at ${width}px`, async ({
    page,
  }, info) => {
    test.skip(process.env.PATENTSAR_E2E_SAR_MUTATIONS !== 'synthetic-isolated-state');
    const errors: string[] = [],
      forbidden: string[] = [],
      imported: string[] = [];
    page.on('pageerror', (error) => errors.push(error.message));
    await page.route('**/api/v1/**', async (route) => {
      const path = new URL(route.request().url()).pathname;
      if (route.request().method() === 'GET') return route.continue();
      if (
        route.request().method() === 'POST' &&
        ['/api/v1/sar/csv/preview', '/api/v1/sar/datasets/csv'].includes(path)
      ) {
        imported.push(path);
        return route.continue();
      }
      forbidden.push(path);
      await route.abort();
    });
    await page.setViewportSize({ width, height: width === 390 ? 844 : 1060 });
    await page.emulateMedia({ reducedMotion: 'reduce' });
    const dataset = await importCSV(page, width);
    const sourcePath =
      '/api/v1/sar/datasets/' + dataset.id + '/molecules?page=1&page_size=50&query=';
    const original = await (await page.request.get(sourcePath)).json();
    expect(original.items.map((row: { label: string }) => row.label)).toEqual([
      'Example 1',
      'I-255',
      '8B',
      'Unresolved',
    ]);
    expect(original.items[0].observations[0].value).toBe('<10');
    expect(original.items[0].observations[0].unit).toBe('nM');
    const setup = page.getByRole('region', { name: 'Study setup', exact: true });
    await setup.locator('.sar-context-choice input').first().check();
    await setup
      .getByRole('combobox', { name: 'Activity direction', exact: true })
      .selectOption('lower');
    await setup.getByRole('button', { name: 'Continue', exact: true }).click();
    await setup.getByText('Add a named selection', { exact: true }).click();
    const picker = page.getByRole('region', { name: 'Choose reference molecule', exact: true });
    const row = picker
      .locator('tbody tr')
      .filter({ has: page.getByRole('rowheader', { name: 'Example 1', exact: true }) });
    await expect(row.locator('td').nth(1)).toHaveText('IC50 (nM): <10');
    const detail = row.locator('td > details');
    const disclosure = detail.locator(':scope > summary');
    const rawRecord = detail.locator('.sar-evidence > ul > li > span');
    await disclosure.click();
    await expect(detail.locator('.sar-evidence > ul > li > span')).toHaveText('IC50 (nM): <10');
    await detail
      .locator('.sar-evidence > ul > li > span')
      .evaluate((element) => element.scrollIntoView({ block: 'center', inline: 'end' }));
    await capture(page, info, '01-source-en');
    await page
      .getByRole('combobox', { name: 'Interface language', exact: true })
      .selectOption('zh-CN');
    await expect(disclosure).toHaveText('来源详情');
    await expect(row.locator('td').nth(1)).toHaveText('IC50 (nM): <10');
    await expect(detail.locator('.sar-evidence > ul > li > span')).toHaveText('IC50 (nM): <10');
    await detail
      .locator('.sar-evidence > ul > li > span')
      .evaluate((element) => element.scrollIntoView({ block: 'center', inline: 'end' }));
    await capture(page, info, '02-source-zh');
    await expect(rawRecord).toBeVisible();
    expect(
      await rawRecord.evaluate((element) => {
        const box = element.getBoundingClientRect(),
          frame = element.closest('.sar-table-scroll')!.getBoundingClientRect();
        return (
          box.left >= Math.max(0, frame.left) &&
          box.right <= Math.min(innerWidth, frame.right) &&
          box.top >= Math.max(0, frame.top) &&
          box.bottom <= Math.min(innerHeight, frame.bottom)
        );
      }),
    ).toBe(true);
    await disclosure.click();
    await row.getByRole('button', { name: '参考', exact: true }).click();
    const selection = page.getByRole('region', { name: '选择变化区域', exact: true });
    await expect(selection.locator('.sar-atom').first()).toBeEnabled();
    await expect(selection).toBeFocused();
    await selection.locator('.sar-atom').first().click();
    await selection.getByLabel('区域名称', { exact: true }).fill('Original 原文 draft');
    await capture(page, info, '03-unsaved-selection-zh');
    expect(await (await page.request.get(sourcePath)).json()).toEqual(original);
    expect(
      (await (await page.request.get('/api/v1/sar/datasets/' + dataset.id + '/jobs')).json()).items,
    ).toEqual([]);
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth + 1)).toBe(
      true,
    );
    expect(errors).toEqual([]);
    expect(forbidden).toEqual([]);
    expect(imported).toEqual(['/api/v1/sar/csv/preview', '/api/v1/sar/datasets/csv']);
  });
}
