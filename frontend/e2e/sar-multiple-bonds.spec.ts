import { expect, test } from '@playwright/test';
import { createNetwork, portSite } from './sar-network-actions';
import { decodeStudyReport } from '../src/api/sarStudyDecoders';

const csv =
  'id,smiles,IC50 (nM),t_half (h),target,assay,cell_line,duration\nA1,O=C1CCNCC1,10,1,T,controlled,C,1h\nA2,S=C1CCNCC1,1,3,T,controlled,C,1h\nA3,O=C1CCOCC1,,4,T,controlled,C,1h\nB1,COc1ccc(C#N)cc1,20,4,T,controlled,C,1h\nB2,COc1ccc(C#C)cc1,2,6,T,controlled,C,1h\n';

for (const width of [390, 1672])
  test(`minimal multiple-bond changes and native activity/PK at ${width}`, async ({
    page,
  }, info) => {
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
    const path = `/api/v1/sar/jobs/${job}/study`;
    const archive = await (await page.request.get(path + '/export?format=json')).text();
    const data = decodeStudyReport((await (await page.request.get(path)).json()).report);
    expect(data.discovery?.multiple_bond_boundaries).toBe(true);
    const rows = (await (await page.request.get(path + '/rows')).json()).items;
    const ids = Object.fromEntries(
      rows.map((row: { label: string; molecule_id: string }) => [row.label, row.molecule_id]),
    );
    await report.getByRole('button', { name: 'Variable regions', exact: true }).click();
    const network = page.locator('.sar-network').filter({ visible: true });
    for (const [left, right, difference] of [
      ['A1', 'A2', '-9.00'],
      ['B1', 'B2', '-18.00'],
    ] as const) {
      await network.getByRole('button', { name: `Select core ${left}`, exact: true }).click();
      const wanted = portSite(data.regions, left, ids[right], 1);
      expect(wanted.item.region.atom_indices).toHaveLength(1);
      await network
        .locator('.sar-region-legend')
        .getByRole('button', { name: `R${wanted.index + 1}`, exact: true })
        .click();
      const matrix = network.getByRole('table', { name: 'Structure comparison', exact: true });
      await expect(matrix.locator('thead th strong')).toHaveText([left, right]);
      await network.getByRole('button', { name: `Compare ${right}`, exact: true }).click();
      const preview = network.getByRole('region', { name: 'Transformation preview', exact: true });
      await expect(
        preview.getByRole('row').filter({ hasText: 'IC50' }).locator('td').last(),
      ).toContainText(difference);
      await expect(
        preview.getByRole('row').filter({ hasText: 't_half' }).locator('td').last(),
      ).toContainText('2.00');
      await page.waitForFunction(() =>
        [...document.querySelectorAll('.sar-network img')]
          .filter((image) => image.checkVisibility())
          .every(
            (image) =>
              (image as HTMLImageElement).complete && (image as HTMLImageElement).naturalWidth > 0,
          ),
      );
      await network.screenshot({ path: info.outputPath(`multiple-${left}-${width}.png`) });
      await preview
        .getByRole('button', { name: 'Close transformation preview', exact: true })
        .click();
    }
    await page.locator('.language-switch select').selectOption('zh-CN');
    await expect(page.getByRole('region', { name: '单点结构对比', exact: true })).toBeVisible();
    await network.screenshot({ path: info.outputPath(`multiple-zh-${width}.png`) });
    expect(await (await page.request.get(path + '/export?format=json')).text()).toBe(archive);
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth + 1)).toBe(
      true,
    );
    expect(errors).toEqual([]);
    expect(foreignWrites).toEqual([]);
  });
