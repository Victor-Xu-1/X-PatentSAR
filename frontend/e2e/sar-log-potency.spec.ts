import { expect, test } from '@playwright/test';

for (const width of [390, 1440])
  test(`automatic concentration-equivalent log potency at ${width}`, async ({ page }, testInfo) => {
    test.skip(process.env.PATENTSAR_E2E_SAR_MUTATIONS !== 'synthetic-isolated-state');
    await page.setViewportSize({ width, height: 1050 });
    const errors: string[] = [];
    page.on('pageerror', (error) => errors.push(error.message));
    await page.goto('/#/sar');
    const imports = page.getByRole('region', { name: 'Import data', exact: true });
    await imports.getByRole('button', { name: 'CSV file', exact: true }).click();
    const logs = [...Array(9).fill('10'), '9', '8', '7', ''];
    const doses = [...Array(9).fill('0.1'), '1', '10', '100', ''];
    const csv =
      'id,smiles,pIC50,IC50 (nM),Dmax (%),target,assay,cell_line,duration\n' +
      logs
        .map(
          (value, index) =>
            `L${index + 1},${'C'.repeat(index + 1)}O,${value},${doses[index]},80,T,binding,C,2h`,
        )
        .join('\n');
    await imports.getByLabel('Choose a CSV file', { exact: true }).setInputFiles({
      name: 'independent-log-potency.csv',
      mimeType: 'text/csv',
      buffer: Buffer.from(csv),
    });
    await imports.getByRole('button', { name: 'Preview on server', exact: true }).click();
    for (const name of ['pIC50', 'IC50 (nM)', 'Dmax (%)'])
      await imports.getByRole('checkbox', { name, exact: true }).check();
    await imports.getByRole('button', { name: 'Create CSV dataset', exact: true }).click();
    const setup = page.getByRole('region', { name: 'Study setup', exact: true });
    for (const name of [/pIC50/, /^IC50/, /Dmax/])
      await setup.getByRole('checkbox', { name }).check();
    await expect(
      setup.getByRole('combobox', { name: 'Activity direction', exact: true }),
    ).toHaveCount(0);
    await setup.getByRole('button', { name: 'Continue', exact: true }).click();
    await setup.getByRole('checkbox', { name: 'Find single-site changes', exact: true }).uncheck();
    await setup.getByRole('button', { name: 'Run full study', exact: true }).click();
    await expect(page).toHaveURL(/job=[a-f0-9]{32}/);
    const job = new URLSearchParams(new URL(page.url()).hash.split('?')[1]).get('job');
    const path = '/api/v1/sar/jobs/' + job + '/study';
    const report = page.getByRole('region', { name: 'Study report', exact: true });
    await expect(report.getByRole('button', { name: 'Activity table', exact: true })).toBeVisible({
      timeout: 20000,
    });
    const archive = await (await page.request.get(path + '/export?format=json')).text();
    const data = (await (await page.request.get(path)).json()).report;
    const byName = Object.fromEntries(
      data.contexts.map((context: { name: string; id: string }) => [context.name, context.id]),
    );
    const scales = Object.fromEntries(
      data.policies.map((policy: { context_id: string; strength_scale: unknown }) => [
        policy.context_id,
        policy.strength_scale,
      ]),
    );
    expect(scales[byName.pIC50]).toMatchObject({
      basis: 'negative_log_molar',
      anchor_rank: 10,
      anchor_lower: 9,
      strong_boundary: 8,
      medium_boundary: 7,
    });
    expect(scales[byName['Dmax (%)']]).toMatchObject({
      status: 'unsupported',
      strong_boundary: null,
    });
    await expect(report).toContainText('Strong >8; medium >7–≤8; weak ≤7');
    await report.screenshot({ path: testInfo.outputPath(`log-distribution-en-${width}.png`) });
    await report.getByRole('button', { name: 'Activity table', exact: true }).click();
    const table = report.locator('table.sar-study-table');
    for (const [label, tier] of [
      ['L10', 'strong'],
      ['L11', 'medium'],
      ['L12', 'weak'],
      ['L13', 'unclassified'],
    ] as const) {
      const row = table
        .getByRole('row')
        .filter({ has: page.getByRole('rowheader', { name: label, exact: true }) });
      await expect(row.locator(`td[data-activity-strength="${tier}"]`)).toHaveCount(
        tier === 'unclassified' ? 3 : 2,
      );
    }
    await page
      .getByRole('combobox', { name: 'Interface language', exact: true })
      .selectOption('zh-CN');
    const boundaryRow = table.getByRole('row').filter({
      has: page.getByRole('rowheader', { name: 'L10', exact: true }),
    });
    await boundaryRow
      .locator('td[data-activity-strength="strong"]')
      .first()
      .evaluate((cell) => cell.scrollIntoView({ block: 'start', inline: 'center' }));
    await page
      .getByRole('region', { name: '研究报告', exact: true })
      .screenshot({ path: testInfo.outputPath(`log-table-zh-${width}.png`) });
    expect(await (await page.request.get(path + '/export?format=json')).text()).toBe(archive);
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth + 1)).toBe(
      true,
    );
    expect(errors).toEqual([]);
  });
