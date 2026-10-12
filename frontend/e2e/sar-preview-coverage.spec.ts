import { expect, test } from '@playwright/test';
import type { StudyReport } from '../src/api/sarStudyTypes';
import { compactNetworkSites } from '../src/features/sar/study/networkSites';
import { regionMarker } from '../src/features/sar/study/regionMarker';

const csv =
  'id,smiles,IC50 (nM),t_half (h),target,assay,cell_line,duration\n' +
  '1,COc1ccc(Cl)cc1,10,1,T,controlled,C,1h\n' +
  '2,CCOc1ccc(Cl)cc1,1,2,T,controlled,C,1h\n' +
  '3,COc1ccc(Br)cc1,0.1,3,T,controlled,C,1h\n' +
  '4,CCCOc1ccc(Cl)cc1,,4,T,controlled,C,1h\n';

for (const width of [390, 800, 1672]) {
  test(`same-site alternatives retain supporting PK and strict source identity at ${width}`, async ({
    page,
  }) => {
    test.skip(process.env.PATENTSAR_E2E_SAR_MUTATIONS !== 'synthetic-isolated-state');
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
    await page.setViewportSize({ width, height: 1060 });
    await page.goto('/#/sar');
    const imports = page.getByRole('region', { name: 'Import data', exact: true });
    await imports.getByRole('button', { name: 'CSV file', exact: true }).click();
    await imports.getByLabel('Choose a CSV file', { exact: true }).setInputFiles({
      name: `preview-source-${width}.csv`,
      mimeType: 'text/csv',
      buffer: Buffer.from(csv),
    });
    await imports.getByRole('button', { name: 'Preview on server', exact: true }).click();
    for (const name of ['IC50 (nM)', 't_half (h)'])
      await imports.getByRole('checkbox', { name, exact: true }).check();
    await imports.getByRole('button', { name: 'Create CSV dataset', exact: true }).click();
    await expect(page).toHaveURL(/dataset=[a-f0-9]{32}/);
    const setup = page.getByRole('region', { name: 'Study setup', exact: true });
    await setup.getByRole('checkbox', { name: /IC50/ }).check();
    await expect(setup.getByRole('checkbox', { name: /t_half/ })).not.toBeChecked();
    await expect(setup.getByRole('status', { name: 'Activity direction', exact: true })).toHaveText(
      'Automatic · Lower is stronger',
    );
    await setup.getByRole('button', { name: 'Continue', exact: true }).click();
    await expect(
      setup.getByRole('checkbox', { name: 'Find single-site changes', exact: true }),
    ).toBeChecked();
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
    const report: StudyReport = (await (await page.request.get(path)).json()).report;
    expect(report.policies).toHaveLength(1);
    const sources = (
      await (await page.request.get('/api/v1/sar/datasets/' + dataset + '/molecules')).json()
    ).items;
    const id = (label: string) => sources.find((row: { label: string }) => row.label === label).id;
    await reportView.getByRole('button', { name: 'Variable regions', exact: true }).click();
    const network = reportView.getByRole('region', {
      name: 'Single-site comparisons',
      exact: true,
    });
    await network.getByRole('textbox', { name: 'Find a core ID', exact: true }).fill('1');
    await network.getByRole('button', { name: 'Select core 1', exact: true }).click();
    const sites = compactNetworkSites(
      report.regions.filter(
        (site) => site.region.molecule_id === id('1') && site.matched && !site.no_variation,
      ),
    );
    const chosen = sites.find((site) =>
      ['2', '4'].every((label) =>
        site.fragments.some(
          (fragment) => !fragment.is_reference && fragment.molecule_ids.includes(id(label)),
        ),
      ),
    )!;
    expect(chosen).toBeDefined();
    const index = sites.indexOf(chosen);
    const alias = { ...chosen.region, name: 'R' + (index + 1) };
    const drawing = await (
      await page.request.get(
        '/api/v1/sar/datasets/' + dataset + '/molecules/' + id('1') + '/drawing',
      )
    ).json();
    const anchor = chosen.region.hydrogen_anchor ?? chosen.region.atom_indices[0]!;
    const atom = drawing.atoms.find((item: { index: number }) => item.index === anchor);
    const hotspot = network.locator('.sar-region-hotspots').getByRole('button', {
      name: regionMarker(alias, index).description + ' · ' + atom.element + ' ' + anchor,
      exact: true,
    });
    await expect(hotspot).toHaveCount(1);
    await hotspot.click();
    await expect(network.getByRole('button', { name: 'Compare 2', exact: true })).toBeVisible();
    await expect(network.getByRole('button', { name: 'Compare 4', exact: true })).toBeVisible();
    await expect(network.getByRole('button', { name: 'Compare 3', exact: true })).toHaveCount(0);
    await network.getByRole('button', { name: 'Compare 2', exact: true }).click();
    const preview = network.getByRole('region', { name: 'Transformation preview', exact: true });
    const members = preview.getByRole('combobox', { name: 'Modified compound', exact: true });
    await expect(members.getByRole('option', { name: '4', exact: true })).toHaveCount(1);
    await expect(members.getByRole('option', { name: '3', exact: true })).toHaveCount(0);
    const pk = preview
      .getByRole('row')
      .filter({ has: page.getByRole('rowheader', { name: 't_half (h)', exact: true }) });
    await expect(pk).toHaveCount(1);
    await expect(pk.locator('td').nth(0)).toContainText('1');
    await expect(pk.locator('td').nth(1)).toContainText('2');
    await expect(pk.getByLabel('Not assessed in this study')).toHaveText('—');
    await expect(pk.locator('td').last()).not.toContainText('Δ');
    const ready = async () =>
      page.waitForFunction(() => {
        const images = [...document.querySelectorAll('.sar-transformation img')].filter((node) =>
          node.checkVisibility(),
        );
        return (
          images.length === 2 &&
          images.every(
            (node) =>
              (node as HTMLImageElement).complete && (node as HTMLImageElement).naturalWidth > 0,
          )
        );
      });
    await ready();
    await preview.screenshot({ path: test.info().outputPath(`preview-all-records-${width}.png`) });
    await members.selectOption(id('4'));
    await expect(preview.locator('.sar-molecule-comparison strong').last()).toHaveText('4');
    await expect(pk.locator('td').nth(1)).toContainText('4');
    const activity = preview
      .getByRole('row')
      .filter({ has: page.getByRole('rowheader', { name: 'IC50 (nM)', exact: true }) });
    await expect(activity.locator('td').nth(1)).toContainText('—');
    await expect(activity.locator('td').last()).not.toContainText('Δ');
    await ready();
    await preview.screenshot({ path: test.info().outputPath(`preview-alternative-${width}.png`) });
    await page
      .getByRole('combobox', { name: 'Interface language', exact: true })
      .selectOption('zh-CN');
    const translatedNetwork = page
      .getByRole('region', { name: '研究报告', exact: true })
      .getByRole('region', { name: '单点结构对比', exact: true });
    const translated = translatedNetwork.getByRole('region', { name: '改造预览', exact: true });
    await expect(translated.getByRole('combobox', { name: '改造化合物', exact: true })).toHaveValue(
      id('4'),
    );
    await expect(
      translated.getByRole('rowheader', { name: 't_half (h)', exact: true }),
    ).toBeVisible();
    await expect(translated.getByLabel('未纳入本次统计')).toHaveText('—');
    await translated.screenshot({
      path: test.info().outputPath(`preview-records-zh-${width}.png`),
    });
    await translated.getByRole('button', { name: '关闭改造预览', exact: true }).click();
    await expect(
      translatedNetwork.getByRole('button', { name: '比较 2', exact: true }),
    ).toBeFocused();
    expect(await (await page.request.get(path + '/export?format=json')).text()).toBe(before);
    const wrong = await page.request.get(
      path +
        '/preview?' +
        new URLSearchParams({ region_id: chosen.region.id, molecule_id: id('3') }),
    );
    expect(wrong.status()).toBe(422);
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth + 1)).toBe(
      true,
    );
    expect(errors).toEqual([]);
    expect(foreignWrites).toEqual([]);
  });
}
