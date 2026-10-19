import { expect, test } from '@playwright/test';
import { decodeDataset } from '../src/api/sarDecoders';

for (const width of [390, 1672]) {
  test(`original table namespaces survive automatic native CSV import at ${width}px`, async ({
    page,
  }) => {
    expect(process.env.PATENTSAR_E2E_SAR_MUTATIONS).toBe('synthetic-isolated-state');
    const errors: string[] = [],
      foreign: string[] = [];
    page.on('pageerror', (error) => errors.push(error.message));
    await page.route('**/api/v1/**', async (route) => {
      const path = new URL(route.request().url()).pathname;
      if (
        route.request().method() !== 'GET' &&
        !['/api/v1/sar/csv/preview', '/api/v1/sar/datasets/csv'].includes(path)
      ) {
        foreign.push(path);
        await route.abort();
      } else await route.continue();
    });
    await page.setViewportSize({ width, height: 1060 });
    await page.goto('/#/sar');
    const panel = page.getByRole('region', { name: 'Import data', exact: true });
    await panel.getByRole('button', { name: 'CSV file', exact: true }).click();
    const quote = (value: string) => `"${value.replaceAll('"', '""')}"`;
    const headers = [
      'review_only',
      'acceptance_state',
      'compound_id',
      'display_id',
      'identifier_label',
      'smiles',
      'metric',
      'value',
      'unit',
      'target',
      'assay',
      'source_page',
      'activity_page',
      'structure_molfile_json',
      'source_scope',
      'source_table',
      'source_context_page',
      'source_conditions_json',
    ];
    const rows = [1, 2].map((table) => [
      'True',
      'failed',
      'internal-id',
      'Example 001B',
      '001B',
      'CO',
      'IC50',
      '<1',
      'nM',
      'TargetA',
      'binding',
      '7',
      '12',
      '',
      String(table).repeat(64),
      `Table ${table}`,
      '11',
      JSON.stringify({ cell_line: 'HEK293', duration: '24 h' }),
    ]);
    await panel.getByLabel('Choose a CSV file', { exact: true }).setInputFiles({
      name: `controlled-source-context-${width}.csv`,
      mimeType: 'text/csv',
      buffer: Buffer.from([headers, ...rows].map((row) => row.map(quote).join(',')).join('\n')),
    });
    await panel.getByRole('button', { name: 'Preview on server', exact: true }).click();
    await expect(
      panel.getByRole('combobox', { name: 'Source identifier column', exact: true }),
    ).toHaveValue('identifier_label');
    await expect(
      panel.getByRole('combobox', { name: 'PDF source-page column (optional)', exact: true }),
    ).toHaveValue('activity_page');
    await panel.getByRole('button', { name: 'Create CSV dataset', exact: true }).click();
    await expect(page).toHaveURL(/dataset=[a-f0-9]{32}/);
    const id = new URLSearchParams(new URL(page.url()).hash.split('?')[1]).get('dataset');
    const prefix = '/api/v1/sar/datasets/' + id;
    const dataset = decodeDataset(await (await page.request.get(prefix)).json());
    expect(dataset.source_kind).toBe('csv');
    expect(dataset.metrics).toHaveLength(2);
    expect(dataset.metrics.map((metric) => metric.source_table)).toEqual(['Table 1', 'Table 2']);
    const records = (await (await page.request.get(prefix + '/molecules')).json()).items;
    expect(records).toHaveLength(1);
    expect(records[0].label).toBe('001B');
    expect(records[0].source_page).toBe(7);
    expect(records[0].observations).toHaveLength(2);
    expect(
      records[0].observations.every(
        (item: { source_page: number; source_kind: string }) =>
          item.source_page === 12 && item.source_kind === 'imported',
      ),
    ).toBe(true);
    const setup = page.getByRole('region', { name: 'Study setup', exact: true });
    for (const table of [1, 2])
      await expect(
        setup.getByRole('checkbox', { name: new RegExp(`Table ${table} · p. 11`) }),
      ).toBeVisible();
    expect(await setup.innerText()).not.toContain('1'.repeat(64));
    await setup.screenshot({ path: test.info().outputPath(`source-context-en-${width}.png`) });
    await page
      .getByRole('combobox', { name: 'Interface language', exact: true })
      .selectOption('zh-CN');
    await page.reload();
    const translated = page.locator('.sar-context-picker');
    await expect(translated.getByRole('checkbox')).toHaveCount(2);
    await expect(translated).toContainText('Table 1 · p. 11');
    await expect(translated).toContainText('Table 2 · p. 11');
    await translated.screenshot({ path: test.info().outputPath(`source-context-zh-${width}.png`) });
    expect(decodeDataset(await (await page.request.get(prefix)).json())).toEqual(dataset);
    expect((await (await page.request.get(prefix + '/jobs')).json()).items).toEqual([]);
    expect(errors).toEqual([]);
    expect(foreign).toEqual([]);
  });
}
