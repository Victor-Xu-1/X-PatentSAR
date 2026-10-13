import { expect, test } from '@playwright/test';
import { createNetwork } from './sar-network-actions';

for (const explicit of [false, true])
  for (const width of [390, 1672])
    test(`unselected ${explicit ? 'declared-unit' : 'bare'} PK difference stays neutral at ${width}`, async ({
      page,
    }, info) => {
      test.skip(process.env.PATENTSAR_E2E_SAR_MUTATIONS !== 'synthetic-isolated-state');
      await page.setViewportSize({ width, height: 1060 });
      const errors: string[] = [],
        writes: string[] = [];
      page.on('pageerror', (error) => errors.push(error.message));
      await page.route('**/api/v1/**', (route) => {
        if (
          route.request().method() !== 'GET' &&
          !new URL(route.request().url()).pathname.startsWith('/api/v1/sar/')
        ) {
          writes.push(route.request().url());
          return route.abort();
        }
        return route.continue();
      });
      const csv = explicit
        ? 'id,smiles,IC50 (nM),t_half (h),target,assay,cell_line,duration\n1,COc1ccc(Cl)cc1,10,1 h,T,controlled,C,1h\n2,CCOc1ccc(Cl)cc1,1,2h,T,controlled,C,1h\n3,COc1ccc(Br)cc1,0.1,3 h,T,controlled,C,1h\n4,CCCOc1ccc(Cl)cc1,,4 h,T,controlled,C,1h\n'
        : undefined;
      const { job, report } = await createNetwork(page, width, csv, false, true);
      const path = `/api/v1/sar/jobs/${job}/study`;
      const archive = await (await page.request.get(path + '/export?format=json')).text();
      expect(JSON.parse(archive).input.schema).toBe(7);
      expect(JSON.parse(archive).report.policies).toHaveLength(1);
      await report.getByRole('button', { name: 'Variable regions', exact: true }).click();
      const network = page.locator('.sar-network').filter({ visible: true });
      await network.getByRole('button', { name: 'Select core 1', exact: true }).click();
      const table = network.getByRole('table', { name: 'Structure comparison', exact: true });
      if (explicit) {
        const sourceValues = table.getByRole('row').filter({ hasText: 't_half' });
        await expect(sourceValues).toContainText('1 h');
        await expect(sourceValues).toContainText('2h');
      }
      await expect(
        table
          .getByRole('row')
          .filter({ hasText: 't_half' })
          .getByLabel('Numeric change; not a ranking'),
      ).toHaveText(['Δ +1.00', 'Δ +2.00', 'Δ +3.00']);
      await network.getByRole('button', { name: 'Compare 2', exact: true }).click();
      const preview = network.getByRole('region', { name: 'Transformation preview', exact: true });
      await expect(
        preview
          .getByRole('row')
          .filter({ hasText: 't_half' })
          .getByLabel('Numeric change; not a ranking'),
      ).toHaveText('Δ +1.00');
      await page.waitForFunction(() =>
        [...document.querySelectorAll('.sar-network img')]
          .filter((item) => item.checkVisibility())
          .every(
            (item) =>
              (item as HTMLImageElement).complete && (item as HTMLImageElement).naturalWidth > 0,
          ),
      );
      await preview.screenshot({ path: info.outputPath(`supporting-en-${width}.png`) });
      await page.locator('.language-switch select').selectOption('zh-CN');
      await expect(
        network
          .getByRole('region', { name: '改造预览', exact: true })
          .getByLabel('数值差，不代表优劣'),
      ).toHaveText('Δ +1.00');
      await network.screenshot({ path: info.outputPath(`supporting-zh-${width}.png`) });
      expect(await (await page.request.get(path + '/export?format=json')).text()).toBe(archive);
      expect(
        await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth + 1),
      ).toBe(true);
      expect(errors).toEqual([]);
      expect(writes).toEqual([]);
    });
