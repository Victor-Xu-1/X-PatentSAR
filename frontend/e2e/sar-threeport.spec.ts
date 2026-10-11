import { expect, test } from '@playwright/test';
import { createNetwork, portSite } from './sar-network-actions';
import { decodeStudyReport } from '../src/api/sarStudyDecoders';

const csv =
  'id,smiles,IC50 (nM),t_half (h),target,assay,cell_line,duration\n1,COC(c1ccccc1)Nc1ncccc1,10,1,T,controlled,C,1h\n2,CON(c1ccccc1)Nc1ncccc1,1,3,T,controlled,C,1h\n3,COC(C)(c1ccccc1)Nc1ncccc1,,4,T,controlled,C,1h\n4,FC1CC2CCC1C2N,20,4,T,controlled,C,1h\n5,FC1CN2CCC1C2N,2,6,T,controlled,C,1h\n';

for (const width of [390, 800, 1672]) {
  test(`three-port branched and bridged-ring previews at ${width}`, async ({ page }) => {
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
    expect(decoded.discovery?.max_cut_bonds).toBe(3);
    const rows = await (await page.request.get(`/api/v1/sar/jobs/${job}/study/rows`)).json();
    const ids = Object.fromEntries(
      rows.items.map((row: { label: string; molecule_id: string }) => [row.label, row.molecule_id]),
    );
    await report.getByRole('button', { name: 'Variable regions', exact: true }).click();
    await expect(page.locator('.sar-network-map').filter({ visible: true })).toHaveCSS(
      'min-width',
      '0px',
    );
    await expect(
      page.locator('.sar-network .sar-reference-map-card').filter({ visible: true }),
    ).toHaveCSS('min-width', '0px');
    for (const [left, right, difference] of [
      ['1', '2', '-9.00'],
      ['4', '5', '-18.00'],
    ]) {
      const network = page.locator('.sar-network').filter({ visible: true });
      await network.getByRole('button', { name: `Select core ${left}`, exact: true }).click();
      const wanted = portSite(decoded.regions, left!, ids[right!], 3);
      await network
        .locator('.sar-region-legend')
        .getByRole('button', { name: `R${wanted.index + 1}`, exact: true })
        .click();
      await network.getByRole('button', { name: `Compare ${right}`, exact: true }).click();
      const preview = network.getByRole('region', { name: 'Transformation preview', exact: true });
      await expect(preview.locator('.sar-molecule-comparison img')).toHaveCount(2);
      await expect(
        preview.getByRole('row').filter({ hasText: 'IC50' }).locator('td').last(),
      ).toContainText(difference!);
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
      await preview.screenshot({ path: test.info().outputPath(`three-port-${left}-${width}.png`) });
      await preview
        .getByRole('button', { name: 'Close transformation preview', exact: true })
        .click();
    }
    await page.locator('.language-switch select').selectOption('zh-CN');
    await expect(page.getByRole('region', { name: '单点结构对比', exact: true })).toBeVisible();
    await page.screenshot({
      path: test.info().outputPath(`three-port-chinese-${width}.png`),
      fullPage: true,
    });
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth + 1)).toBe(
      true,
    );
    expect(errors).toEqual([]);
    expect(foreignWrites).toEqual([]);
  });
}
