import { expect, test } from '@playwright/test';
import type { StudyReport } from '../src/api/sarStudyTypes';
import { compactNetworkSites } from '../src/features/sar/study/networkSites';

const cases = [
  {
    name: 'bare intervals',
    headers: 'IC50 (nM),Dmax (%)',
    reference: '>10,<80',
    candidate: '<10,>=80',
    other: '1,90',
    potency: ['>10', '<10Better'],
    efficacy: ['<80', '>=80Better'],
    intervals: true,
  },
  {
    name: 'explicit inline units',
    headers: 'IC50,Dmax',
    reference: '10 nM,70%',
    candidate: '0.002 µM,80%',
    other: '1 nM,90%',
    potency: ['10 nM', '0.002 µMΔ -8.00'],
    efficacy: ['70%', '80%Δ +10.00'],
    intervals: false,
  },
] as const;

for (const scenario of cases)
  test(`native ${scenario.name} preserve measurement semantics in the structure matrix`, async ({
    page,
  }, testInfo) => {
    test.skip(process.env.PATENTSAR_E2E_SAR_MUTATIONS !== 'synthetic-isolated-state');
    const errors: string[] = [];
    page.on('pageerror', (error) => errors.push(error.message));
    await page.goto('/#/sar');
    const imports = page.getByRole('region', { name: 'Import data', exact: true });
    await imports.getByRole('button', { name: 'CSV file', exact: true }).click();
    await imports.getByLabel('Choose a CSV file', { exact: true }).setInputFiles({
      name: 'controlled-intervals.csv',
      mimeType: 'text/csv',
      buffer: Buffer.from(
        `id,smiles,${scenario.headers},CL (mL/min/kg),target,assay,cell_line,duration\n` +
          `A1,COc1ccc(Cl)cc1,${scenario.reference},2,T,controlled,C,2h\n` +
          `A2,CCOc1ccc(Cl)cc1,${scenario.candidate},3,T,controlled,C,2h\n` +
          `A3,CCOc1ccc(Br)cc1,${scenario.other},4,T,controlled,C,2h\n`,
      ),
    });
    await imports.getByRole('button', { name: 'Preview on server', exact: true }).click();
    for (const name of [...scenario.headers.split(','), 'CL (mL/min/kg)'])
      await imports.getByRole('checkbox', { name, exact: true }).check();
    await imports.getByRole('button', { name: 'Create CSV dataset', exact: true }).click();
    const setup = page.getByRole('region', { name: 'Study setup', exact: true });
    for (const name of [/IC50/, /Dmax/]) await setup.getByRole('checkbox', { name }).check();
    await expect(setup.getByRole('checkbox', { name: /CL/ })).not.toBeChecked();
    await setup.getByRole('button', { name: 'Continue', exact: true }).click();
    await setup.getByRole('button', { name: 'Run full study', exact: true }).click();
    await expect(page).toHaveURL(/job=[a-f0-9]{32}/);
    const params = new URLSearchParams(new URL(page.url()).hash.split('?')[1]);
    const job = params.get('job')!,
      dataset = params.get('dataset')!;
    const path = '/api/v1/sar/jobs/' + job + '/study';
    const reportView = page.getByRole('region', { name: 'Study report', exact: true });
    await expect(
      reportView.getByRole('button', { name: 'Variable regions', exact: true }),
    ).toBeVisible({ timeout: 20000 });
    const before = await (await page.request.get(path + '/export?format=json')).text();
    expect(JSON.parse(before).input.schema).toBe(5);
    const report: StudyReport = (await (await page.request.get(path)).json()).report;
    expect(report.candidate_policy).toBe('strict-context-pareto-units-v3');
    const sources = (
      await (await page.request.get('/api/v1/sar/datasets/' + dataset + '/molecules')).json()
    ).items;
    const id = (label: string) => sources.find((row: { label: string }) => row.label === label).id;
    await reportView.getByRole('button', { name: 'Variable regions', exact: true }).click();
    const network = reportView.getByRole('region', {
      name: 'Single-site comparisons',
      exact: true,
    });
    await network.getByRole('textbox', { name: 'Find a core ID', exact: true }).fill('A1');
    await network.getByRole('button', { name: 'Select core A1', exact: true }).click();
    const sites = compactNetworkSites(
      report.regions.filter(
        (site) => site.region.molecule_id === id('A1') && site.matched && !site.no_variation,
      ),
    );
    const index = sites.findIndex(
      (site) =>
        site.fragments.some(
          (fragment) => !fragment.is_reference && fragment.molecule_ids.includes(id('A2')),
        ) && !site.fragments.some((fragment) => fragment.molecule_ids.includes(id('A3'))),
    );
    expect(index).toBeGreaterThanOrEqual(0);
    await network.locator('.sar-region-legend button').nth(index).click();
    const matrix = network.getByRole('table', { name: 'Structure comparison', exact: true });
    await expect(matrix.locator('thead th strong')).toHaveText(['A1', 'A2']);
    for (const [label, values] of [
      [scenario.intervals ? 'IC50 (nM)' : 'IC50 · nM', scenario.potency],
      [scenario.intervals ? 'Dmax (%)' : 'Dmax · %', scenario.efficacy],
      ['CL (mL/min/kg)', ['2', '3']],
    ] as const) {
      const row = matrix.getByRole('rowheader', { name: label, exact: true }).locator('..');
      await expect(row.getByRole('cell')).toHaveText([...values]);
      if (scenario.intervals || label === 'CL (mL/min/kg)')
        await expect(row).not.toContainText('Δ');
    }
    await page.waitForFunction(() =>
      [...document.querySelectorAll('.sar-network img')]
        .filter((image) => image.checkVisibility())
        .every(
          (image) =>
            (image as HTMLImageElement).complete && (image as HTMLImageElement).naturalWidth > 0,
        ),
    );
    await network.screenshot({ path: testInfo.outputPath('interval-matrix-en.png') });
    await network.getByRole('button', { name: 'Compare A2', exact: true }).click();
    const preview = network.getByRole('region', { name: 'Transformation preview', exact: true });
    await expect(preview.locator('.sar-delta.is-better')).toHaveCount(2);
    await preview
      .getByRole('button', { name: 'Close transformation preview', exact: true })
      .click();
    await page
      .getByRole('combobox', { name: 'Interface language', exact: true })
      .selectOption('zh-CN');
    const localized = page.getByRole('region', { name: '单点结构对比', exact: true });
    if (scenario.intervals)
      await expect(
        localized
          .getByRole('table', { name: '结构对照', exact: true })
          .getByText('SAR 更强', { exact: true }),
      ).toHaveCount(2);
    else await expect(localized.locator('.sar-matrix-delta.is-better')).toHaveCount(2);
    await localized.screenshot({ path: testInfo.outputPath('interval-matrix-zh.png') });
    expect(await (await page.request.get(path + '/export?format=json')).text()).toBe(before);
    expect(errors).toEqual([]);
  });
