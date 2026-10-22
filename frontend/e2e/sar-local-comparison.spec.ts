import { expect, test } from '@playwright/test';
import { createNetwork } from './sar-network-actions';
import { compactNetworkSites, networkRowSites } from '../src/features/sar/study/networkSites';
import type { CatalogRegion } from '../src/api/sarCatalogTypes';

for (const width of [390, 800, 1672]) {
  test(`local comparison defaults and responsive pairs at ${width}`, async ({ page }) => {
    test.skip(process.env.PATENTSAR_E2E_SAR_MUTATIONS !== 'synthetic-isolated-state');
    await page.setViewportSize({ width, height: 1060 });
    const errors: string[] = [];
    page.on('pageerror', (e) => errors.push(e.message));
    const { job, report } = await createNetwork(page, width, undefined, false, true);
    const path = `/api/v1/sar/jobs/${job}/study`;
    const original = await (await page.request.get(path + '/export?format=json')).text();
    const catalog = (await (await page.request.get(path + '/catalog')).json()).report;
    let lastSelections: URLSearchParams | undefined;
    let matrixReads = 0;
    page.on('request', (request) => {
      const url = new URL(request.url());
      if (url.pathname === path + '/matrix') {
        matrixReads++;
        lastSelections = url.searchParams;
      }
    });
    await report.getByRole('button', { name: 'Variable regions', exact: true }).click();
    const network = page.getByRole('region', { name: 'Single-site comparisons', exact: true });
    const matrix = network.locator('.sar-network-matrix');
    await expect(
      matrix.getByRole('table', { name: 'Structure comparison', exact: true }),
    ).toBeVisible();
    const map = network.locator('.sar-reference-map-image');
    await page.waitForFunction(() => {
      const image = document.querySelector<HTMLImageElement>('.sar-reference-map-image img');
      return image?.complete && image.naturalWidth > 0;
    });
    const label = (await map.locator('img').getAttribute('alt'))!;
    const source = await map.locator('img').getAttribute('src');
    const enlarge = map.getByRole('button', { name: 'Enlarge structure ' + label, exact: true });
    await enlarge.click();
    const focus = page.getByRole('dialog', { name: 'Molecular preview · ' + label, exact: true });
    await expect(focus.getByRole('img', { name: label, exact: true })).toHaveAttribute(
      'src',
      source!,
    );
    await focus.press('Escape');
    await expect(enlarge).toBeFocused();
    if (width > 1000) {
      const left = await network.locator('.sar-reference-map-card').boundingBox();
      const right = await matrix.boundingBox();
      expect(left!.x + left!.width).toBeLessThan(right!.x);
      expect(Math.abs(left!.y - right!.y)).toBeLessThan(30);
      expect(
        await network
          .getByRole('textbox', { name: 'Find a core ID', exact: true })
          .evaluate((node) => node.getBoundingClientRect().width),
      ).toBeLessThanOrEqual(320);
    }
    await expect.poll(() => lastSelections?.getAll('molecule_id').length ?? 0).toBeGreaterThan(0);
    const ids = lastSelections!.getAll('molecule_id'),
      regions = lastSelections!.getAll('region_id');
    const ref = lastSelections!.get('reference_id');
    const sites = compactNetworkSites(
      catalog.regions.filter(
        (site: CatalogRegion) =>
          site.region.molecule_id === ref && site.matched && !site.no_variation,
      ),
    );
    for (const [index, id] of ids.entries())
      expect(regions[index]).toBe(networkRowSites(sites, id)[0]?.region.id);
    const settledReads = matrixReads;
    await page.setViewportSize({ width: 390, height: 1060 });
    const selector = matrix.getByRole('combobox', { name: 'Comparison molecule', exact: true });
    await expect(selector).toBeVisible();
    const options = await selector
      .locator('option')
      .evaluateAll((nodes) => nodes.map((n) => (n as HTMLOptionElement).value));
    expect(options.length).toBe(ids.length);
    await selector.selectOption(options.at(-1)!);
    await expect(
      matrix.getByRole('button', { name: 'Next structures', exact: true }),
    ).toBeDisabled();
    await page.waitForFunction(() => {
      const images = [...document.querySelectorAll<HTMLImageElement>('.sar-matrix-table img')];
      return images.length === 2 && images.every((i) => i.complete && i.naturalWidth > 0);
    });
    const headers = matrix.getByRole('columnheader');
    const boxes = await headers.evaluateAll((nodes) =>
      nodes.slice(1).map((n) => n.getBoundingClientRect().toJSON()),
    );
    for (const box of boxes) {
      expect(box.x).toBeGreaterThanOrEqual(0);
      expect(box.right).toBeLessThanOrEqual(390);
      expect(box.width).toBeGreaterThan(140);
    }
    await matrix.screenshot({ path: test.info().outputPath(`paired-${width}.png`) });
    await page
      .getByRole('combobox', { name: 'Interface language', exact: true })
      .selectOption('zh-CN');
    await expect(page.getByRole('combobox', { name: '对比分子', exact: true })).toHaveValue(
      options.at(-1)!,
    );
    await page.setViewportSize({ width: 1672, height: 1060 });
    await expect(page.getByRole('combobox', { name: '对比分子', exact: true })).toHaveCount(0);
    const desktop = page.locator('.sar-network-matrix');
    await expect(desktop.getByRole('columnheader')).toHaveCount(ids.length + 2);
    await desktop.screenshot({ path: test.info().outputPath(`matrix-${width}.png`) });
    expect(matrixReads).toBe(settledReads);
    expect(await (await page.request.get(path + '/export?format=json')).text()).toBe(original);
    expect(errors).toEqual([]);
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth + 1)).toBe(
      true,
    );
  });
}
