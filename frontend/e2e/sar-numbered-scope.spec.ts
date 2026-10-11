import { expect, test } from '@playwright/test';

for (const width of [390, 1672]) {
  test(`numbered SAR import and tenth-decade result at ${width}`, async ({ page }) => {
    test.skip(process.env.PATENTSAR_E2E_SAR_MUTATIONS !== 'synthetic-isolated-state');
    await page.setViewportSize({ width, height: 1060 });
    const errors: string[] = [],
      foreignWrites: string[] = [];
    page.on('pageerror', (error) => errors.push(error.message));
    await page.route('**/api/v1/**', (route) => {
      if (
        route.request().method() !== 'GET' &&
        !new URL(route.request().url()).pathname.startsWith('/api/v1/sar/')
      ) {
        foreignWrites.push(route.request().url());
        return route.abort();
      }
      return route.continue();
    });
    await page.goto('/#/sar');
    const imports = page.getByRole('region', { name: 'Import data', exact: true });
    await imports.getByRole('button', { name: 'CSV file', exact: true }).click();
    const values = [...Array<string>(9).fill('0.1'), '1', '9', '10', '99', '100', ''];
    const csv = [
      'id,smiles,IC50 (nM),target,assay,cell_line,duration',
      ...['', '-', 'N/A', 'NaN', 'None', '未编号', '无编号', 'Intermediate 18'].map(
        (label) => `${label},CO,0.000001,T,binding,C,1h`,
      ),
      ...values.map(
        (value, index) =>
          `I-${index + 1},${'C'.repeat(index + 1)}Oc1ccc(Cl)cc1,${value},T,binding,C,1h`,
      ),
      '8B,,,T,binding,C,1h',
    ].join('\n');
    await imports.getByLabel('Choose a CSV file', { exact: true }).setInputFiles({
      name: `numbered-scope-${width}.csv`,
      mimeType: 'text/csv',
      buffer: Buffer.from(csv),
    });
    await imports.getByRole('button', { name: 'Preview on server', exact: true }).click();
    for (const [label, column] of [
      ['Source identifier column', 'id'],
      ['SMILES column', 'smiles'],
      ['Target column (optional)', 'target'],
      ['Assay column (optional)', 'assay'],
      ['Cell-line column (optional)', 'cell_line'],
      ['Duration column (optional)', 'duration'],
    ] as const)
      await imports.getByRole('combobox', { name: label, exact: true }).selectOption(column);
    await imports.getByRole('checkbox', { name: 'IC50 (nM)', exact: true }).check();
    await imports.getByRole('button', { name: 'Create CSV dataset', exact: true }).click();
    await expect(page).toHaveURL(/dataset=[a-f0-9]{32}/);
    const dataset = new URLSearchParams(new URL(page.url()).hash.split('?')[1]).get('dataset');
    const metadata = await (await page.request.get(`/api/v1/sar/datasets/${dataset}`)).json();
    expect([metadata.input_row_count, metadata.row_count]).toEqual([24, 16]);
    const setup = page.getByRole('region', { name: 'Study setup', exact: true });
    await setup.getByRole('checkbox', { name: /IC50/ }).check();
    await setup
      .getByRole('combobox', { name: 'Activity direction', exact: true })
      .selectOption('lower');
    await setup.getByRole('button', { name: 'Continue', exact: true }).click();
    await setup.getByRole('checkbox', { name: 'Find single-site changes', exact: true }).uncheck();
    await setup.getByRole('button', { name: 'Run full study', exact: true }).click();
    await expect(page).toHaveURL(/job=[a-f0-9]{32}/);
    const job = new URLSearchParams(new URL(page.url()).hash.split('?')[1]).get('job');
    const report = page.getByRole('region', { name: 'Study report', exact: true });
    await expect(report.locator('.sar-study-tabs')).toBeVisible({ timeout: 30000 });
    const path = `/api/v1/sar/jobs/${job}/study`;
    const current = await (await page.request.get(path)).json();
    const scale = current.report.policies[0].strength_scale;
    expect([
      scale.anchor_rank,
      scale.anchor_lower,
      scale.strong_boundary,
      scale.medium_boundary,
    ]).toEqual([10, 1, 10, 100]);
    const bins = Object.fromEntries(
      current.report.distributions[0].bins.map((bin: { label: string; molecules: number }) => [
        bin.label,
        bin.molecules,
      ]),
    );
    expect([bins.strong, bins.medium, bins.weak, bins.missing]).toEqual([11, 2, 1, 2]);
    const all = await (await page.request.get(path + '/rows?page_size=200')).json();
    expect(all.total).toBe(16);
    expect(all.items.map((row: { label: string }) => row.label).sort()).toEqual(
      [...values.map((_, index) => `I-${index + 1}`), '8B'].sort(),
    );
    expect(
      all.items.find((row: { label: string }) => row.label === 'I-15').properties.molecular_weight,
    ).toBeGreaterThan(0);
    expect(all.items.find((row: { label: string }) => row.label === '8B').eligible).toBe(false);
    expect(
      (await (await page.request.get(path + '/rows?scope=strong&page_size=1')).json()).total,
    ).toBe(11);
    expect((await (await page.request.get(path + '/rows?page=2&page_size=1')).json()).total).toBe(
      16,
    );
    expect((await (await page.request.get(path)).json()).report.policies[0].strength_scale).toEqual(
      scale,
    );
    const exported = await (await page.request.get(path + '/export?format=json')).json();
    expect(exported.input.molecules).toHaveLength(16);
    expect(exported.activity_view.report.molecule_count).toBe(16);
    const csvExport = await (await page.request.get(path + '/export?format=csv')).text();
    expect(csvExport).toContain('tenth_decade');
    expect(csvExport).not.toContain('Intermediate 18');
    expect(csvExport).not.toContain('N/A');
    for (const locale of ['en', 'zh-CN']) {
      await page.locator('.language-switch select').selectOption(locale);
      await report.locator('.sar-study-tabs button').nth(0).click();
      await expect(report.locator('.sar-policy-note')).toHaveCount(1);
      await expect(report.locator('.sar-policy-note')).toContainText(/10 nM/);
      await page.screenshot({
        path: `${process.env.PATENTSAR_E2E_OUTPUT_DIR}/numbered-overview-${locale}-${width}.png`,
        fullPage: true,
      });
      await report.locator('.sar-study-tabs button').nth(5).click();
      await expect(report.locator('table tbody tr')).toHaveCount(16);
      await page.waitForFunction(() =>
        [...document.querySelectorAll('.sar-study-report img')]
          .filter((el) => el.checkVisibility())
          .every(
            (el) => (el as HTMLImageElement).complete && (el as HTMLImageElement).naturalWidth > 0,
          ),
      );
      await page.screenshot({
        path: `${process.env.PATENTSAR_E2E_OUTPUT_DIR}/numbered-table-${locale}-${width}.png`,
      });
    }
    await page.reload();
    await expect(page.locator('.sar-study-report table tbody tr')).toHaveCount(16);
    expect(errors).toEqual([]);
    expect(foreignWrites).toEqual([]);
  });
}
