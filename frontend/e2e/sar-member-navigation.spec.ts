import { expect, test } from '@playwright/test';
import { syntheticSnapshot } from './sarSnapshotFixture';
import { cardProtocol } from './sarCardProtocolFixture';

for (const width of [390, 800, 1672]) {
  test(`explicit member choices reveal the table once at ${width}px`, async ({ page }, info) => {
    test.skip(process.env.PATENTSAR_E2E_SAR_MUTATIONS !== 'synthetic-isolated-state');
    const errors: string[] = [],
      writes: string[] = [];
    page.on('pageerror', (error) => errors.push(error.message));
    await page.route('**/api/v1/**', (route) => {
      if (route.request().method() === 'GET') return route.continue();
      writes.push(new URL(route.request().url()).pathname);
      return route.abort();
    });
    await page.setViewportSize({ width, height: width === 390 ? 844 : 1060 });
    await page.emulateMedia({ reducedMotion: 'reduce' });
    const dataset = await syntheticSnapshot(page);
    const fixture = await cardProtocol(page, dataset);
    const original = JSON.stringify(fixture.report);
    const report = page.getByRole('region', { name: 'Study report', exact: true });
    for (const view of ['Scaffolds', 'Variable regions', 'Fragment summary']) {
      await report.getByRole('button', { name: view, exact: true }).click();
      const source = report.getByRole('region', { name: view, exact: true });
      await source.getByRole('button', { name: 'View molecules', exact: true }).first().click();
      const table = report.getByRole('region', { name: 'Activity table', exact: true });
      await expect(table).toBeFocused();
      await expect
        .poll(() => table.evaluate((element) => element.getBoundingClientRect().top))
        .toBeLessThan(50);
      await expect(table.getByRole('table')).toBeVisible();
      await expect(table.getByRole('rowheader')).toHaveText(fixture.molecule.label);
      expect(fixture.rowRequests.at(-1)).toMatchObject(
        view === 'Scaffolds'
          ? { scope: 'all', scaffold_id: 'core/control', region_id: '', fragment_id: '' }
          : {
              scope: 'all',
              scaffold_id: '',
              region_id: fixture.report.regions[0]!.region.id,
              fragment_id: 'fragment/control',
            },
      );
      await page.screenshot({
        path: info.outputPath(view + '-members.png'),
        animations: 'disabled',
      });
      const search = table.getByRole('searchbox', {
        name: 'Search identifiers or SMILES',
        exact: true,
      });
      await search.fill(fixture.molecule.label);
      await expect.poll(() => fixture.rowRequests.at(-1)?.query).toBe(fixture.molecule.label);
      await expect(search).toBeFocused();
      await page
        .getByRole('combobox', { name: 'Interface language', exact: true })
        .selectOption('zh-CN');
      const localized = page.getByRole('region', { name: '研究活性表', exact: true });
      await expect(localized.getByRole('rowheader')).toHaveText(fixture.molecule.label);
      await expect(page.getByRole('combobox', { name: '界面语言', exact: true })).toBeFocused();
      await page.getByRole('combobox', { name: '界面语言', exact: true }).selectOption('en');
    }
    const jobs = await page.request.get(`/api/v1/sar/datasets/${dataset.id}/jobs`);
    expect((await jobs.json()).items).toEqual([]);
    expect(JSON.stringify(fixture.report)).toBe(original);
    expect(errors).toEqual([]);
    expect(writes).toEqual([]);
  });
}
