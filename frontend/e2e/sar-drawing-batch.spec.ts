import { expect, test } from '@playwright/test';
import { createNetwork } from './sar-network-actions';

// Real frontend -> service -> receipt reader -> RDKit on generated CSV only.
// Repeated simple graphs intentionally exercise distinct source-record IDs.
const csv =
  'id,smiles,IC50 (nM),t_half (h),target,assay,cell_line,duration\n' +
  Array.from(
    { length: 40 },
    (_, n) =>
      `${n + 1},${['COc1ccc(Cl)cc1', 'CCOc1ccc(Cl)cc1', 'COc1ccc(Br)cc1', 'CCCOc1ccc(Cl)cc1'][n % 4]},${n + 1},1,T,controlled,C,1h\n`,
  ).join('');

for (const width of [390, 1672]) {
  test(`bounded real drawing batches and language-safe report at ${width}`, async ({
    page,
  }, info) => {
    test.skip(process.env.PATENTSAR_E2E_SAR_MUTATIONS !== 'synthetic-isolated-state');
    await page.setViewportSize({ width, height: 1060 });
    const errors: string[] = [],
      batches: URL[] = [],
      singles: string[] = [];
    page.on('pageerror', (error) => errors.push(error.message));
    page.on('request', (request) => {
      const url = new URL(request.url());
      if (url.pathname.endsWith('/study/drawings')) {
        expect(request.method()).toBe('GET');
        batches.push(url);
      }
      if (url.pathname.endsWith('/study/drawing')) singles.push(url.pathname);
    });
    const { job, report } = await createNetwork(page, width, csv, true, true);
    await report.getByRole('button', { name: 'Activity table', exact: true }).click();
    const table = report.getByRole('region', { name: 'Activity table', exact: true });
    await expect(table.locator('.sar-study-image img')).toHaveCount(40);
    await page.waitForFunction(() => {
      const pictures = [
        ...document.querySelectorAll<HTMLImageElement>('.sar-study-table .sar-study-image img'),
      ];
      return (
        pictures.length > 0 && pictures.every((image) => image.complete && image.naturalWidth > 0)
      );
    });
    const molecules = batches.filter(
      (url) => url.pathname.includes(job) && url.searchParams.get('kind') === 'molecule',
    );
    expect(molecules.some((url) => url.searchParams.getAll('identifier').length > 1)).toBe(true);
    expect(batches.every((url) => url.searchParams.getAll('identifier').length <= 32)).toBe(true);
    expect(singles).toEqual([]);
    await expect(table.getByRole('alert')).toHaveCount(0);
    await table.screenshot({ path: info.outputPath(`drawing-batch-${width}-en.png`) });
    await page
      .getByRole('combobox', { name: 'Interface language', exact: true })
      .selectOption('zh-CN');
    await expect(page.locator('.sar-study-image img')).toHaveCount(40);
    await page.screenshot({ path: info.outputPath(`drawing-batch-${width}-zh.png`) });
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth + 1)).toBe(
      true,
    );
    expect(errors).toEqual([]);
  });
}
