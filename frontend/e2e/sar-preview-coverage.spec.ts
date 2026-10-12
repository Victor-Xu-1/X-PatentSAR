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
    await expect(network.getByRole('combobox', { name: 'Core order', exact: true })).toHaveValue(
      'alternatives',
    );
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
    const matrix = network.getByRole('table', { name: 'Structure comparison', exact: true });
    await expect(matrix).toBeVisible();
    await expect(matrix.getByRole('columnheader')).toHaveCount(4);
    const potencyRow = matrix
      .getByRole('rowheader', { name: 'IC50 (nM)', exact: true })
      .locator('..');
    await expect(potencyRow.getByRole('cell')).toHaveText(['10', '1Δ -9.00', '—Not measured']);
    const matrixPK = matrix
      .getByRole('rowheader', { name: 't_half (h)', exact: true })
      .locator('..');
    await expect(matrixPK.getByRole('cell')).toHaveText(['1', '2', '4']);
    await expect(matrixPK).not.toContainText('Δ');
    for (const label of ['MW', 'LogP', 'TPSA', 'HBD', 'HBA', 'LogS'])
      await expect(matrix.getByRole('rowheader', { name: label, exact: true })).toHaveCount(1);
    if (width < 1000) {
      await network.getByRole('button', { name: 'Next structures', exact: true }).click();
      await expect
        .poll(() => network.locator('.sar-matrix-viewport').evaluate((node) => node.scrollLeft))
        .toBeGreaterThan(0);
      await network.locator('.sar-matrix-viewport').scrollIntoViewIfNeeded();
      const visibility = await matrix.evaluate((node) => {
        const pane = node.closest('.sar-matrix-viewport')!.getBoundingClientRect();
        const cells = [...node.querySelectorAll<HTMLTableCellElement>('thead th')];
        const reference = cells[1]!;
        const style = getComputedStyle(reference);
        const frozen =
          style.position === 'sticky' && style.left !== 'auto'
            ? reference.getBoundingClientRect().right
            : cells[0]!.getBoundingClientRect().right;
        return cells.slice(2).flatMap((cell) => {
          const box = cell.getBoundingClientRect();
          const visible = Math.max(0, Math.min(box.right, pane.right) - Math.max(box.left, frozen));
          if (visible < box.width / 2) return [];
          const label = cell.querySelector('strong')!,
            rect = label.getBoundingClientRect();
          const hit = document.elementFromPoint(rect.x + rect.width / 2, rect.y + rect.height / 2);
          return [!!hit && label.closest('button')!.contains(hit)];
        });
      });
      expect(visibility.length).toBeGreaterThan(0);
      expect(visibility.every(Boolean)).toBe(true);
    }
    await network.getByRole('button', { name: 'Compare 2', exact: true }).click();
    const preview = network.getByRole('region', { name: 'Transformation preview', exact: true });
    const members = preview.getByRole('combobox', { name: 'Modified compound', exact: true });
    const paired = await page.request.get(
      path +
        '/preview?' +
        new URLSearchParams({
          region_id: chosen.region.id,
          molecule_id: id('2'),
        }),
    );
    expect(paired.ok()).toBe(true);
    const drawingPair = (await paired.json()).drawings;
    expect(drawingPair.layout).toBe('fixed_component');
    expect(drawingPair.reference.id).toBe(id('1'));
    expect(drawingPair.candidate.id).toBe(id('2'));
    expect(drawingPair.equivalent_mappings).toBeGreaterThanOrEqual(1);
    expect(drawingPair.reason).toBeNull();
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
    await expect(preview.locator('.sar-molecule-comparison')).toHaveAttribute(
      'data-layout',
      'fixed_component',
    );
    for (const figure of await preview.locator('.sar-molecule-comparison figure').all()) {
      const geometry = await figure.evaluate((node) => {
        const image = node.querySelector('img')!;
        return {
          canvas: node.getBoundingClientRect().width,
          image: image.getBoundingClientRect().width,
        };
      });
      expect(Math.abs(geometry.canvas - geometry.image)).toBeLessThanOrEqual(1);
    }
    await preview.getByRole('button', { name: 'Enlarge structure 2', exact: true }).click();
    const focus = page.getByRole('dialog');
    await expect(focus.getByRole('img', { name: '2', exact: true })).toBeVisible();
    await focus.getByRole('button', { name: 'Zoom in structure', exact: true }).click();
    await expect(
      focus.getByRole('status', { name: 'Magnification relative to fit', exact: true }),
    ).toHaveText('125%');
    await page.keyboard.press('Escape');
    await expect(
      preview.getByRole('button', { name: 'Enlarge structure 2', exact: true }),
    ).toBeFocused();
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
