import { expect, test } from '@playwright/test';
import { createNetwork, portSite } from './sar-network-actions';
import { decodeStudyReport } from '../src/api/sarStudyDecoders';

const csv =
  'id,smiles,IC50 (nM),t_half (h),target,assay,cell_line,duration\n1,COc1ccccc1Cl,10,1,T,controlled,C,1h\n2,COc1ccncc1Cl,1,3,T,controlled,C,1h\n3,COc1cnccc1Cl,,4,T,controlled,C,1h\n';

for (const width of [390, 800, 1672]) {
  test(`aromatic atom changes and labelled subgraph previews at ${width}`, async ({ page }) => {
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
    const { job, report } = await createNetwork(page, width, csv);
    const overview = await (await page.request.get(`/api/v1/sar/jobs/${job}/study`)).json();
    const decoded = decodeStudyReport(overview.report);
    expect(decoded.discovery?.aromatic_boundaries).toBe(true);
    const rows = await (await page.request.get(`/api/v1/sar/jobs/${job}/study/rows`)).json();
    const ids = Object.fromEntries(
      rows.items.map((row: { label: string; molecule_id: string }) => [row.label, row.molecule_id]),
    );
    await report.getByRole('button', { name: 'Variable regions', exact: true }).click();
    const network = page.locator('.sar-network').filter({ visible: true });
    await network.getByRole('button', { name: 'Select core 1', exact: true }).click();
    const wanted = portSite(decoded.regions, '1', ids['2'], 2);
    expect(wanted.item.region.atom_indices).toHaveLength(1);
    await network
      .locator('.sar-region-legend')
      .getByRole('button', { name: `R${wanted.index + 1}`, exact: true })
      .click();
    await network.getByRole('button', { name: 'Compare 2', exact: true }).click();
    const preview = network.getByRole('region', { name: 'Transformation preview', exact: true });
    await expect(
      preview.getByRole('row').filter({ hasText: 'IC50' }).locator('td').last(),
    ).toContainText('-9.00');
    await expect(
      preview.getByRole('row').filter({ hasText: 't_half' }).locator('td').last(),
    ).toContainText('2.00');
    await page.waitForFunction(() =>
      [...document.querySelectorAll('.sar-network img')]
        .filter((el) => el.checkVisibility())
        .every(
          (el) => (el as HTMLImageElement).complete && (el as HTMLImageElement).naturalWidth > 0,
        ),
    );
    await preview.screenshot({ path: test.info().outputPath(`aromatic-comparison-${width}.png`) });
    await report.getByRole('button', { name: 'Fragment summary', exact: true }).click();
    await expect(report.getByText('Aromatic subgraph', { exact: false }).first()).toBeVisible();
    await page.waitForFunction(() =>
      [...document.querySelectorAll('.sar-study-card img')]
        .filter((el) => el.checkVisibility())
        .every(
          (el) => (el as HTMLImageElement).complete && (el as HTMLImageElement).naturalWidth > 0,
        ),
    );
    await report.screenshot({ path: test.info().outputPath(`aromatic-fragments-${width}.png`) });
    await page.locator('.language-switch select').selectOption('zh-CN');
    const localizedReport = page.getByRole('region', { name: '研究报告', exact: true });
    await expect(localizedReport.getByText('芳香子图', { exact: false }).first()).toBeVisible();
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth + 1)).toBe(
      true,
    );
    expect(errors).toEqual([]);
    expect(foreignWrites).toEqual([]);
  });
}
