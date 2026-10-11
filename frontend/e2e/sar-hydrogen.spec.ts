import { expect, test } from '@playwright/test';
import { createNetwork } from './sar-network-actions';
import { compactNetworkSites } from '../src/features/sar/study/networkSites';
import { decodeStudyReport } from '../src/api/sarStudyDecoders';

const csv =
  'id,smiles,IC50 (nM),t_half (h),target,assay,cell_line,duration\n1,COc1ccccc1Cl,10,1,T,controlled,C,1h\n2,COc1c(F)cccc1Cl,1,2,T,controlled,C,1h\n3,COc1c(C)cccc1Cl,,3,T,controlled,C,1h\n4,COc1ccc(F)cc1Cl,0.1,4,T,controlled,C,1h\n';

for (const width of [390, 800, 1672]) {
  test(`source-bound H modifications and reverse previews at ${width}`, async ({ page }) => {
    test.skip(process.env.PATENTSAR_E2E_SAR_MUTATIONS !== 'synthetic-isolated-state');
    await page.setViewportSize({ width, height: 1060 });
    const errors: string[] = [];
    page.on('pageerror', (error) => errors.push(error.message));
    const { job, dataset, report } = await createNetwork(page, width, csv);
    const snapshot = await (await page.request.get(`/api/v1/sar/jobs/${job}/study`)).json();
    const data = decodeStudyReport(snapshot.report);
    expect(data.discovery?.method).toBe('single-region-one-to-three-cut-h-v4');
    const rows = await (await page.request.get(`/api/v1/sar/jobs/${job}/study/rows`)).json();
    const ids = Object.fromEntries(
      rows.items.map((row: { label: string; molecule_id: string }) => [row.label, row.molecule_id]),
    );
    await report.getByRole('button', { name: 'Variable regions', exact: true }).click();
    const network = page.locator('.sar-network').filter({ visible: true });
    for (const [left, right, hydrogen] of [
      ['1', '2', true],
      ['2', '1', false],
    ] as const) {
      await network.getByRole('button', { name: 'Select core ' + left, exact: true }).click();
      const visible = compactNetworkSites(
        data.regions.filter(
          (item) => item.reference_label === left && item.matched && !item.no_variation,
        ),
      );
      const index = visible.findIndex(
        (item) =>
          (item.region.hydrogen_anchor != null) === hydrogen &&
          item.fragments.some((fragment) => fragment.molecule_ids.includes(ids[right])),
      );
      expect(index).toBeGreaterThanOrEqual(0);
      await network.locator('.sar-region-legend button').nth(index).click();
      await network.getByRole('button', { name: 'Compare ' + right, exact: true }).click();
      const preview = network.getByRole('region', { name: 'Transformation preview', exact: true });
      await expect(preview.locator('.sar-molecule-comparison img')).toHaveCount(2);
      await expect(
        preview.getByRole('row').filter({ hasText: 'IC50' }).locator('td').last(),
      ).toContainText(hydrogen ? '-9.00' : '+9.00');
      await expect(
        preview.getByRole('row').filter({ hasText: 't_half' }).locator('td').last(),
      ).toContainText(hydrogen ? '+1.00' : '-1.00');
      await page.waitForFunction(() =>
        [...document.querySelectorAll('.sar-network img')]
          .filter((el) => el.checkVisibility())
          .every(
            (el) => (el as HTMLImageElement).complete && (el as HTMLImageElement).naturalWidth > 0,
          ),
      );
      await network.getByRole('textbox', { name: 'Find a core ID', exact: true }).focus();
      await network.screenshot({ path: test.info().outputPath(`hydrogen-${left}-${width}.png`) });
      await preview
        .getByRole('button', { name: 'Close transformation preview', exact: true })
        .click();
    }
    await page.locator('.language-switch select').selectOption('zh-CN');
    await expect(network.getByRole('button', { name: '选择核心 2', exact: true })).toBeVisible();
    await network.getByRole('textbox', { name: '查找核心编号', exact: true }).focus();
    const skip = page.locator('.skip-link');
    await skip.focus();
    await expect(skip).toBeFocused();
    expect(await skip.evaluate((element) => getComputedStyle(element).clipPath)).toBe('none');
    await skip.press('Enter');
    await expect(page.locator('#main-content')).toBeFocused();
    expect(await skip.evaluate((element) => getComputedStyle(element).clipPath)).toBe('inset(50%)');
    await network.getByRole('textbox', { name: '查找核心编号', exact: true }).focus();
    await network.screenshot({ path: test.info().outputPath(`hydrogen-zh-${width}.png`) });
    expect((await (await page.request.get(`/api/v1/sar/jobs/${job}/study`)).json()).report).toEqual(
      snapshot.report,
    );
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth + 1)).toBe(
      true,
    );
    await page.goto('/#/sar?dataset=' + dataset);
    await page.locator('.language-switch select').selectOption('en');
    await page.getByText('Single-reference comparison (advanced)', { exact: true }).click();
    const references = page.getByRole('region', { name: 'Choose reference molecule', exact: true });
    await references.getByRole('button', { name: 'Reference', exact: true }).first().click();
    const selection = page.getByRole('region', { name: 'Select variable region', exact: true });
    await selection.getByRole('button', { name: 'Atom 3 (C)', exact: true }).click();
    await expect(selection.getByRole('checkbox', { name: 'H site', exact: true })).toBeEnabled();
    await selection.getByRole('checkbox', { name: 'H site', exact: true }).check();
    await selection.getByRole('button', { name: 'Save region', exact: true }).click();
    await expect(
      selection.getByText('Region saved · 1 attachment points', { exact: true }),
    ).toBeVisible();
    const saved = await (await page.request.get(`/api/v1/sar/datasets/${dataset}/profile`)).json();
    expect(saved.regions.at(-1)).toMatchObject({
      atom_indices: [],
      hydrogen_anchor: 3,
      kind: 'variable',
    });
    await selection.screenshot({ path: test.info().outputPath(`manual-hydrogen-${width}.png`) });
    expect(errors).toEqual([]);
  });
}
