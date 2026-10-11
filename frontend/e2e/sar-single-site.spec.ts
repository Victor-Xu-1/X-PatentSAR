import { expect, test, type Page } from '@playwright/test';
import { readFile } from 'node:fs/promises';

async function createNetwork(page: Page, width: number) {
  await page.goto('/#/sar');
  const imports = page.getByRole('region', { name: 'Import data', exact: true });
  await imports.getByRole('button', { name: 'CSV file', exact: true }).click();
  const csv =
    'id,smiles,IC50 (nM),t_half (h),target,assay,cell_line,duration\n1,COc1ccc(Cl)cc1,10,1,T,controlled,C,1h\n2,CCOc1ccc(Cl)cc1,1,2,T,controlled,C,1h\n3,COc1ccc(Br)cc1,0.1,3,T,controlled,C,1h\n4,CCCOc1ccc(Cl)cc1,,4,T,controlled,C,1h\n,CO,0.00001,99,T,controlled,C,1h\nIntermediate 18,CCO,0.00001,99,T,controlled,C,1h\n';
  await imports.getByLabel('Choose a CSV file', { exact: true }).setInputFiles({
    name: `single-site-${width}.csv`,
    mimeType: 'text/csv',
    buffer: Buffer.from(csv),
  });
  await imports.getByRole('button', { name: 'Preview on server', exact: true }).click();
  await imports
    .getByRole('combobox', { name: 'Source identifier column', exact: true })
    .selectOption('id');
  await imports
    .getByRole('combobox', { name: 'SMILES column', exact: true })
    .selectOption('smiles');
  for (const name of ['IC50 (nM)', 't_half (h)'])
    await imports.getByRole('checkbox', { name, exact: true }).check();
  for (const [label, column] of [
    ['Target column (optional)', 'target'],
    ['Assay column (optional)', 'assay'],
    ['Cell-line column (optional)', 'cell_line'],
    ['Duration column (optional)', 'duration'],
  ] as const)
    await imports.getByRole('combobox', { name: label, exact: true }).selectOption(column);
  await imports.getByRole('button', { name: 'Create CSV dataset', exact: true }).click();
  await expect(page).toHaveURL(/dataset=[a-f0-9]{32}/);
  const setup = page.getByRole('region', { name: 'Study setup', exact: true });
  await setup.getByRole('checkbox', { name: /IC50/ }).check();
  await setup.getByRole('checkbox', { name: /t_half/ }).check();
  await setup
    .getByRole('combobox', { name: 'Activity direction', exact: true })
    .nth(1)
    .selectOption('higher');
  await setup.getByRole('button', { name: 'Continue', exact: true }).click();
  await expect(
    setup.getByRole('checkbox', { name: 'Find single-site changes', exact: true }),
  ).toBeChecked();
  await setup.getByRole('button', { name: 'Run full study', exact: true }).click();
  await expect(page).toHaveURL(/job=[a-f0-9]{32}/);
  const params = new URLSearchParams(new URL(page.url()).hash.split('?')[1]);
  const job = params.get('job')!,
    dataset = params.get('dataset')!;
  const report = page.getByRole('region', { name: 'Study report', exact: true });
  await expect(report.getByRole('button', { name: 'Variable regions', exact: true })).toBeVisible({
    timeout: 20000,
  });
  return { job, dataset, report };
}

for (const width of [390, 800, 1672]) {
  test(`multiple native cores, atom sites, PK deltas and export at ${width}`, async ({ page }) => {
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
    const { job, report } = await createNetwork(page, width);
    const overview = await (await page.request.get(`/api/v1/sar/jobs/${job}/study`)).json();
    expect(overview.report.molecule_count).toBe(4);
    expect(overview.report.discovery.method).toBe('single-non-ring-bond-v1');
    const all = await (await page.request.get(`/api/v1/sar/jobs/${job}/study/rows`)).json();
    const candidate = all.items.find((row: { label: string }) => row.label === '2');
    const site = overview.report.regions.find(
      (item: { reference_label: string; fragments: { molecule_ids: string[] }[] }) =>
        item.reference_label === '1' &&
        item.fragments.some((fragment) => fragment.molecule_ids.includes(candidate.molecule_id)),
    );
    await report.getByRole('button', { name: 'Variable regions', exact: true }).click();
    const network = report.getByRole('region', { name: 'Single-site comparisons', exact: true });
    await expect(network).toBeVisible();
    await network.getByRole('button', { name: 'Select core 1', exact: true }).click();
    await network
      .locator('.sar-region-legend')
      .getByRole('button', { name: site.region.name, exact: true })
      .click();
    await expect(network.getByRole('button', { name: 'Compare 2', exact: true })).toBeVisible();
    await page.waitForFunction(() =>
      [...document.querySelectorAll('.sar-network img')]
        .filter((el) => el.checkVisibility())
        .every(
          (el) => (el as HTMLImageElement).complete && (el as HTMLImageElement).naturalWidth > 0,
        ),
    );
    await network.screenshot({ path: test.info().outputPath(`network-${width}.png`) });
    await network.getByRole('button', { name: 'Compare 2', exact: true }).click();
    const preview = network.getByRole('region', { name: 'Transformation preview', exact: true });
    await expect(preview.locator('.sar-molecule-comparison img')).toHaveCount(2);
    const activity = preview.getByRole('row').filter({ hasText: 'IC50' });
    await expect(activity.locator('td').last()).toContainText('-9.00');
    const pk = preview.getByRole('row').filter({ hasText: 't_half' });
    await expect(pk.locator('td').last()).toContainText('1.00');
    await preview.screenshot({ path: test.info().outputPath(`network-comparison-${width}.png`) });
    await preview
      .getByRole('button', { name: 'Close transformation preview', exact: true })
      .click();
    await expect(network.getByRole('button', { name: 'Compare 2', exact: true })).toBeFocused();
    await network
      .getByRole('textbox', { name: 'Find a core ID', exact: true })
      .fill('not-a-source-id');
    await expect(network.getByText('No core structures to show', { exact: true })).toBeVisible();
    await expect(network.locator('.sar-network-layout')).toHaveCount(0);
    await network.getByRole('textbox', { name: 'Find a core ID', exact: true }).fill('');
    await expect(network.getByRole('button', { name: 'Select core 1', exact: true })).toBeVisible();
    const downloading = page.waitForEvent('download');
    await report.getByLabel('Export format', { exact: true }).selectOption('json');
    await report.getByRole('button', { name: 'Export report JSON', exact: true }).click();
    const download = await downloading;
    const exported = JSON.parse(await readFile((await download.path())!, 'utf8'));
    expect(exported.input.request.discover_single_sites).toBe(true);
    expect(exported.report.rows).toHaveLength(4);
    expect(exported.report.discovery.candidate_sites).toBeGreaterThan(4);
    await page
      .getByRole('combobox', { name: 'Interface language', exact: true })
      .selectOption('zh-CN');
    const chinese = page
      .getByRole('region', { name: '单点结构对比', exact: true })
      .filter({ visible: true });
    await expect(chinese.getByRole('button', { name: '选择核心 1', exact: true })).toBeVisible();
    await expect(chinese.getByRole('img', { name: '1', exact: true }).first()).toBeVisible();
    await page.screenshot({
      path: test.info().outputPath(`network-chinese-${width}.png`),
      fullPage: true,
    });
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth + 1)).toBe(
      true,
    );
    expect(errors).toEqual([]);
    expect(foreignWrites).toEqual([]);
    await page.reload();
    await expect(page.getByRole('region', { name: '研究报告', exact: true })).toBeVisible();
  });
}
