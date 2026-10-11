import { expect, test } from '@playwright/test';
import { createNetwork } from './sar-network-actions';
import palette from '../../src/patent_sar_extractor/web/sar/chart_palette.json';

const csv =
  'id,smiles,IC50 (nM),t_half (h),target,assay,cell_line,duration\n' +
  Array.from({ length: 13 }, (_, index) =>
    [
      String(index + 1),
      'C'.repeat(index + 1) + 'Oc1ccc(Cl)cc1',
      index < 9 ? (index + 1) / 10 : index === 9 ? 1 : index === 10 ? 10 : index === 11 ? 100 : '',
      index + 1,
      'T',
      'controlled',
      'C',
      '1h',
    ].join(','),
  ).join('\n');

for (const width of [390, 1672]) {
  test(`count-driven chart colors and percentages at ${width}`, async ({ page }) => {
    test.skip(process.env.PATENTSAR_E2E_SAR_MUTATIONS !== 'synthetic-isolated-state');
    await page.setViewportSize({ width, height: 1060 });
    const errors: string[] = [];
    page.on('pageerror', (error) => errors.push(error.message));
    const { job, report } = await createNetwork(page, width, csv);
    const before = await (await page.request.get(`/api/v1/sar/jobs/${job}/study`)).json();
    const first = page.locator('.sar-overview-charts .sar-study-card').first();
    await expect(first.locator('.sar-donut-number')).toHaveText('13');
    await expect(first.locator('.sar-donut-share')).toHaveText('Strong 76.9%');
    const actualBins = before.report.distributions[0].bins as {
      label: keyof typeof palette;
      molecules: number;
    }[];
    const circles = await first
      .locator('circle')
      .evaluateAll((nodes) => nodes.map((node) => node.getAttribute('stroke')));
    expect(circles).toEqual(
      actualBins.filter((bin) => bin.molecules > 0).map((bin) => palette[bin.label]),
    );
    const colors = await first
      .locator('.sar-chart-track')
      .evaluateAll((nodes) => nodes.map((node) => (node as HTMLElement).style.color));
    const expected = await page.evaluate(
      (hex) =>
        hex.map((color) => {
          const el = document.createElement('span');
          el.style.color = color;
          return el.style.color;
        }),
      actualBins.map((bin) => palette[bin.label]),
    );
    expect(colors).toEqual(expected);
    await expect(
      page.locator('.sar-overview-charts .sar-study-card').nth(1).locator('.sar-donut-share'),
    ).toHaveCount(0);
    await first.screenshot({ path: test.info().outputPath(`activity-chart-${width}.png`) });
    await report.getByRole('button', { name: 'Scaffolds', exact: true }).click();
    const scaffold = page.locator('.sar-study-card').filter({ visible: true }).first();
    await expect(scaffold.locator('.sar-donut-number')).toHaveText('13');
    await expect(scaffold.locator('.sar-donut-share')).toHaveText('Strong 76.9%');
    await scaffold.getByRole('combobox', { name: 'Counting unit' }).selectOption('observations');
    await expect(scaffold.locator('.sar-donut-share')).toHaveText('Strong 76.9%');
    await page.locator('.language-switch select').selectOption('zh-CN');
    await expect(scaffold.locator('.sar-donut-share')).toHaveText('强活性 76.9%');
    await scaffold.screenshot({ path: test.info().outputPath(`scaffold-share-${width}.png`) });
    expect((await (await page.request.get(`/api/v1/sar/jobs/${job}/study`)).json()).report).toEqual(
      before.report,
    );
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth + 1)).toBe(
      true,
    );
    expect(errors).toEqual([]);
  });
}
