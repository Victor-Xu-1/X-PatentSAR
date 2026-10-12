import { expect, test } from '@playwright/test';

for (const width of [390, 800, 1672]) {
  test(`CSV roles are software-owned with explicit ambiguity at ${width}px`, async ({ page }) => {
    test.skip(process.env.PATENTSAR_E2E_SAR_MUTATIONS !== 'synthetic-isolated-state');
    const errors: string[] = [],
      forbidden: string[] = [];
    page.on('pageerror', (error) => errors.push(error.message));
    await page.route('**/api/v1/**', async (route) => {
      const path = new URL(route.request().url()).pathname;
      if (route.request().method() !== 'GET' && !path.startsWith('/api/v1/sar/')) {
        forbidden.push(path);
        await route.abort();
      } else await route.continue();
    });
    await page.setViewportSize({ width, height: width === 390 ? 844 : 1060 });
    await page.goto('/#/sar');
    const panel = page.getByRole('region', { name: 'Import data', exact: true });
    await panel.getByRole('button', { name: 'CSV file', exact: true }).click();
    const csv =
      'Compound ID,SMILES,IC50 (nM),MW,LogP,TPSA,HBD,HBA,LogS,Assay,Cell Line,Duration,Target,PDF Page,predicted hERG,Year\nI-1,CO,1,32,0.4,20,1,2,-1,binding,C,1h,T,7,0.1,2026\nI-2,CCO,,46,0.8,30,1,2,-2,binding,C,1h,T,8,0.2,2026\nIntermediate 9,CO,0.001,32,0.4,20,1,2,-1,binding,C,1h,T,7,0.1,2026\n';
    await panel.getByLabel('Choose a CSV file', { exact: true }).setInputFiles({
      name: `known-roles-${width}.csv`,
      mimeType: 'text/csv',
      buffer: Buffer.from(csv),
    });
    await panel.getByRole('button', { name: 'Preview on server', exact: true }).click();
    await expect(
      panel.getByRole('combobox', { name: 'Source identifier column', exact: true }),
    ).toHaveValue('Compound ID');
    await expect(panel.getByRole('combobox', { name: 'SMILES column', exact: true })).toHaveValue(
      'SMILES',
    );
    for (const [label, value] of [
      ['Assay column (optional)', 'Assay'],
      ['Cell-line column (optional)', 'Cell Line'],
      ['Duration column (optional)', 'Duration'],
      ['Target column (optional)', 'Target'],
      ['PDF source-page column (optional)', 'PDF Page'],
    ] as const)
      await expect(panel.getByRole('combobox', { name: label, exact: true })).toHaveValue(value);
    await expect(panel.getByRole('checkbox', { name: 'IC50 (nM)', exact: true })).toBeChecked();
    for (const name of [
      'MW',
      'LogP',
      'TPSA',
      'HBD',
      'HBA',
      'LogS',
      'Year',
      'PDF Page',
      'predicted hERG',
    ])
      await expect(panel.getByRole('checkbox', { name, exact: true })).not.toBeChecked();
    await expect(
      panel.getByRole('button', { name: 'Create CSV dataset', exact: true }),
    ).toBeEnabled();
    await page.screenshot({
      path: test.info().outputPath(`csv-defaults-${width}.png`),
      fullPage: true,
    });
    await panel
      .getByText('Captured properties and predictions (optional)', { exact: true })
      .click();
    for (const [key, value] of [
      ['molecular_weight', 'MW'],
      ['logP', 'LogP'],
      ['tpsa', 'TPSA'],
      ['hydrogen_bond_donors', 'HBD'],
      ['hydrogen_bond_acceptors', 'HBA'],
      ['Solubility_AqSolDB', 'LogS'],
      ['hERG', 'predicted hERG'],
    ] as const)
      await expect(panel.getByRole('combobox', { name: key, exact: true })).toHaveValue(value);
    await page
      .getByRole('combobox', { name: 'Interface language', exact: true })
      .selectOption('zh-CN');
    await page.screenshot({
      path: test.info().outputPath(`csv-research-zh-${width}.png`),
      fullPage: true,
    });
    await page.getByRole('combobox', { name: '界面语言', exact: true }).selectOption('en');
    await panel.getByRole('button', { name: 'Create CSV dataset', exact: true }).click();
    await expect(page).toHaveURL(/dataset=[a-f0-9]{32}/);
    const id = new URLSearchParams(new URL(page.url()).hash.split('?')[1]).get('dataset');
    const prefix = '/api/v1/sar/datasets/' + id;
    const dataset = await (await page.request.get(prefix)).json();
    expect(dataset.row_count).toBe(2);
    expect(dataset.input_row_count).toBe(3);
    expect(dataset.metrics.map((metric: { name: string }) => metric.name)).toEqual(['IC50 (nM)']);
    const records = await (await page.request.get(prefix + '/molecules')).json();
    expect(records.items.map((row: { label: string }) => row.label)).toEqual(['I-1', 'I-2']);
    expect(records.items[1].observations[0].value).toBe('');
    expect(records.items[1].properties.molecular_weight).toBe(46);
    expect(records.items[0].predictions.hERG).toBe(0.1);
    expect(records.items[0].prediction_origin).toBe('imported');
    expect(records.items[0].observations[0].context).toMatchObject({
      assay: 'binding',
      cell_line: 'C',
      duration: '1h',
      target: 'T',
    });
    expect(records.items[0].observations[0].source_page).toBe(7);
    expect((await (await page.request.get(prefix + '/jobs')).json()).items).toEqual([]);
    await page.getByRole('button', { name: 'Import data', exact: true }).click();
    await panel.getByRole('button', { name: 'CSV file', exact: true }).click();
    await panel.getByLabel('Choose a CSV file', { exact: true }).setInputFiles({
      name: `ambiguous-${width}.csv`,
      mimeType: 'text/csv',
      buffer: Buffer.from('id,SMILES,smiles,IC50 (nM),Mystery\n1,CO,CCO,1,0.1\n'),
    });
    await panel.getByRole('button', { name: 'Preview on server', exact: true }).click();
    await expect(panel.getByRole('combobox', { name: 'SMILES column', exact: true })).toHaveValue(
      '',
    );
    await expect(panel.getByRole('checkbox', { name: 'Mystery', exact: true })).not.toBeChecked();
    await expect(
      panel
        .getByRole('combobox', { name: 'SMILES column', exact: true })
        .locator('option[value=""]'),
    ).toHaveText('Choose a column');
    await expect(
      panel.getByRole('button', { name: 'Create CSV dataset', exact: true }),
    ).toBeDisabled();
    await page.screenshot({
      path: test.info().outputPath(`csv-ambiguity-${width}.png`),
      fullPage: true,
    });
    expect(errors).toEqual([]);
    expect(forbidden).toEqual([]);
  });
}
