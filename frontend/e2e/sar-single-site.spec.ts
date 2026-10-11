import { expect, test } from '@playwright/test';
import { createNetwork } from './sar-network-actions';
import { readFile } from 'node:fs/promises';
import {
  studyProperties,
  differenceText,
  propertyText,
} from '../src/features/sar/study/tablePresentation';

for (const width of [390, 800, 1672]) {
  test(`multiple native cores, atom sites, PK deltas and export at ${width}`, async ({ page }) => {
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
    const { job, report } = await createNetwork(page, width);
    const overview = await (await page.request.get(`/api/v1/sar/jobs/${job}/study`)).json();
    expect(overview.report.molecule_count).toBe(4);
    expect(overview.report.discovery.method).toBe('single-region-three-port-aromatic-h-v5');
    const all = await (await page.request.get(`/api/v1/sar/jobs/${job}/study/rows`)).json();
    const candidate = all.items.find((row: { label: string }) => row.label === '2');
    const site = overview.report.regions.find(
      (item: { reference_label: string; fragments: { molecule_ids: string[] }[] }) =>
        item.reference_label === '1' &&
        item.fragments.some((fragment) => fragment.molecule_ids.includes(candidate.molecule_id)),
    );
    await report.getByRole('button', { name: 'Variable regions', exact: true }).click();
    const network = report.getByRole('region', { name: 'Single-site comparisons', exact: true });
    await expect(network).toBeVisible();
    await network.getByRole('button', { name: 'Select core 1', exact: true }).click();
    const visibleSites = overview.report.regions.filter(
      (item: { reference_label: string; matched: number; no_variation: boolean }) =>
        item.reference_label === '1' && item.matched && !item.no_variation,
    );
    const legend = network.locator('.sar-region-legend button');
    const compactCount = await legend.count();
    expect(compactCount).toBeLessThanOrEqual(visibleSites.length);
    if (compactCount < visibleSites.length) {
      await network.getByRole('button', { name: /^All sites \(/ }).click();
      await expect(legend).toHaveCount(visibleSites.length);
      await network.getByRole('button', { name: 'Compact sites', exact: true }).click();
      await expect(legend).toHaveCount(compactCount);
      await network.getByRole('button', { name: /^All sites \(/ }).click();
    }
    const siteIndex = visibleSites.findIndex(
      (item: { region: { id: string } }) => item.region.id === site.region.id,
    );
    await network
      .locator('.sar-region-legend')
      .getByRole('button', { name: 'R' + (siteIndex + 1), exact: true })
      .click();
    await expect(network.getByRole('button', { name: 'Compare 2', exact: true })).toBeVisible();
    await page.waitForFunction(() =>
      [...document.querySelectorAll('.sar-network img')]
        .filter((el) => el.checkVisibility())
        .every(
          (el) => (el as HTMLImageElement).complete && (el as HTMLImageElement).naturalWidth > 0,
        ),
    );
    expect(
      await network.locator('.sar-network-branch > .sar-study-image').evaluateAll((figures) =>
        figures.every((figure) => {
          const button = figure.querySelector('.sar-image-focus-action');
          if (!button) return true;
          const bounds = figure.getBoundingClientRect(),
            control = button.getBoundingClientRect();
          return (
            control.top >= bounds.top - 1 &&
            control.bottom <= bounds.bottom + 1 &&
            control.left >= bounds.left - 1 &&
            control.right <= bounds.right + 1
          );
        }),
      ),
    ).toBe(true);
    await network.screenshot({ path: test.info().outputPath(`network-${width}.png`) });
    await network.getByRole('button', { name: 'Compare 2', exact: true }).click();
    const preview = network.getByRole('region', { name: 'Transformation preview', exact: true });
    await expect(preview.locator('.sar-molecule-comparison img')).toHaveCount(2);
    const activity = preview.getByRole('row').filter({ hasText: 'IC50' });
    await expect(activity.locator('td').last()).toContainText('-9.00');
    const pk = preview.getByRole('row').filter({ hasText: 't_half' });
    await expect(pk.locator('td').last()).toContainText('1.00');
    const actual = await (
      await page.request.get(
        `/api/v1/sar/jobs/${job}/study/preview?region_id=${site.region.id}&molecule_id=${candidate.molecule_id}`,
      )
    ).json();
    const properties = preview.getByRole('table', { name: 'Properties', exact: true });
    await expect(properties.getByRole('row')).toHaveCount(4);
    const propertyRows = properties.locator('tbody tr');
    for (const [index, row] of [actual.reference, actual.candidate].entries()) {
      await expect(propertyRows.nth(index).getByRole('rowheader')).toHaveText(row.label);
      await expect(propertyRows.nth(index).getByRole('cell')).toHaveText(
        studyProperties.map((property) => propertyText(row.properties[property.key], property.key)),
      );
    }
    await expect(propertyRows.nth(2).getByRole('cell')).toHaveText(
      studyProperties.map((property) => {
        const value = actual.property_differences[property.key];
        return (value != null && value > 0 ? '+' : '') + differenceText(value, property.key);
      }),
    );
    const values = await properties.locator('tbody').innerText();
    await page.locator('.language-switch select').selectOption('zh-CN');
    const localized = page.getByRole('table', { name: '性质', exact: true });
    expect(await localized.locator('tbody').innerText()).toBe(values);
    await page.locator('.language-switch select').selectOption('en');
    if (width === 390) {
      const viewport = preview.locator('.sar-property-comparison');
      expect(await viewport.evaluate((element) => element.scrollWidth > element.clientWidth)).toBe(
        true,
      );
      await viewport.focus();
      await viewport.press('ArrowRight');
      await expect
        .poll(() => viewport.evaluate((element) => element.scrollLeft))
        .toBeGreaterThan(0);
      const aligned = await propertyRows
        .first()
        .getByRole('rowheader')
        .evaluate((cell) => {
          const port = cell.closest('.sar-property-comparison')!.getBoundingClientRect();
          const box = cell.getBoundingClientRect();
          return box.left >= port.left - 1 && box.right <= port.right + 1;
        });
      expect(aligned).toBe(true);
      await viewport.evaluate((element) => {
        element.scrollLeft = 0;
      });
    }
    await preview.screenshot({ path: test.info().outputPath(`network-comparison-${width}.png`) });
    await preview
      .getByRole('button', { name: 'Close transformation preview', exact: true })
      .click();
    await expect(network.getByRole('button', { name: 'Compare 2', exact: true })).toBeFocused();
    await network
      .getByRole('textbox', { name: 'Find a core ID', exact: true })
      .fill('not-a-source-id');
    await expect(network.getByText('No core structures to show', { exact: true })).toBeVisible();
    await expect(network.locator('.sar-network-layout')).toHaveCount(0);
    await network.getByRole('textbox', { name: 'Find a core ID', exact: true }).fill('');
    await expect(network.getByRole('button', { name: 'Select core 1', exact: true })).toBeVisible();
    const downloading = page.waitForEvent('download');
    await report.getByLabel('Export format', { exact: true }).selectOption('json');
    await report.getByRole('button', { name: 'Export report JSON', exact: true }).click();
    const download = await downloading;
    const exported = JSON.parse(await readFile((await download.path())!, 'utf8'));
    expect(exported.input.request.discover_single_sites).toBe(true);
    expect(exported.report.rows).toHaveLength(4);
    expect(exported.report.discovery.candidate_sites).toBeGreaterThan(4);
    await page
      .getByRole('combobox', { name: 'Interface language', exact: true })
      .selectOption('zh-CN');
    const chinese = page
      .getByRole('region', { name: '单点结构对比', exact: true })
      .filter({ visible: true });
    await expect(chinese.getByRole('button', { name: '选择核心 1', exact: true })).toBeVisible();
    await expect(chinese.getByRole('img', { name: '1', exact: true }).first()).toBeVisible();
    await page.screenshot({
      path: test.info().outputPath(`network-chinese-${width}.png`),
      fullPage: true,
    });
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth + 1)).toBe(
      true,
    );
    expect(errors).toEqual([]);
    expect(foreignWrites).toEqual([]);
    await page.reload();
    await expect(page.getByRole('region', { name: '研究报告', exact: true })).toBeVisible();
  });
}
