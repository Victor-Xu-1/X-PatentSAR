import { expect, test } from '@playwright/test';
import type { Page } from '@playwright/test';
import { readFile } from 'node:fs/promises';

async function persisted(page: Page, kind: 'dataset' | 'job') {
  await expect(page).toHaveURL(new RegExp(`(?:\\?|&)${kind}=[a-f0-9]{32}`));
  const id = new URLSearchParams(new URL(page.url()).hash.split('?')[1]).get(kind);
  const response = await page.request.get(
    `/api/v1/sar/${kind === 'dataset' ? 'datasets' : 'jobs'}/${id}`,
  );
  expect(response.status()).toBe(200);
  return response.json();
}

for (const width of [390, 800, 1672]) {
  test(`independent study, all research views and full export at ${width}px`, async ({ page }) => {
    test.skip(process.env.PATENTSAR_E2E_SAR_MUTATIONS !== 'synthetic-isolated-state');
    const errors: string[] = [];
    const foreignWrites: string[] = [];
    page.on('pageerror', (error) => errors.push(error.message));
    await page.route('**/api/v1/**', async (route) => {
      const path = new URL(route.request().url()).pathname;
      if (route.request().method() !== 'GET' && !path.startsWith('/api/v1/sar/')) {
        foreignWrites.push(path);
        await route.abort();
      } else await route.continue();
    });
    await page.setViewportSize({ width, height: width === 390 ? 844 : 1060 });
    await page.goto('/#/sar');
    const imports = page.getByRole('region', { name: 'Import data', exact: true });
    await imports.getByRole('button', { name: 'CSV file', exact: true }).click();
    const csv = [
      'id,smiles,IC50 (nM),target,assay,cell_line,duration',
      'Example 1,COc1ccc(Cl)cc1,10,T,binding,not applicable,1h',
      'Example 2,CCOc1ccc(Cl)cc1,1,T,binding,not applicable,1h',
      'Example 3,CCCOc1ccc(Cl)cc1,2,T,binding,not applicable,1h',
      'Example 4,CCOc1ccc(Br)cc1,0.5,T,binding,not applicable,1h',
      'Example 5,COc1ccc(Cl)cc1,,T,binding,not applicable,1h',
    ].join('\n');
    await imports.getByLabel('Choose a CSV file', { exact: true }).setInputFiles({
      name: `study-${width}.csv`,
      mimeType: 'text/csv',
      buffer: Buffer.from(csv),
    });
    await imports.getByRole('button', { name: 'Preview on server', exact: true }).click();
    await imports
      .getByRole('combobox', { name: 'Source identifier column', exact: true })
      .selectOption('id');
    await imports
      .getByRole('combobox', { name: 'SMILES column', exact: true })
      .selectOption('smiles');
    await imports.getByRole('checkbox', { name: 'IC50 (nM)', exact: true }).check();
    for (const [label, column] of [
      ['Target column (optional)', 'target'],
      ['Assay column (optional)', 'assay'],
      ['Cell-line column (optional)', 'cell_line'],
      ['Duration column (optional)', 'duration'],
    ] as const) {
      await imports.getByRole('combobox', { name: label, exact: true }).selectOption(column);
    }
    await imports.getByRole('button', { name: 'Create CSV dataset', exact: true }).click();
    const dataset = await persisted(page, 'dataset');
    expect(dataset.row_count).toBe(5);
    const setup = page.getByRole('region', { name: 'Study setup', exact: true });
    await expect(setup).toBeVisible();
    await setup.getByRole('checkbox', { name: /IC50/ }).check();
    await setup
      .getByRole('combobox', { name: 'Activity direction', exact: true })
      .selectOption('lower');
    await setup.getByText('Grades and threshold (optional)', { exact: true }).click();
    await setup
      .getByLabel('Strong-activity threshold (optional, raw value)', { exact: true })
      .fill('2');
    await setup.getByText('Add a named selection', { exact: true }).click();
    const browser = setup.getByRole('region', { name: 'Choose reference molecule', exact: true });
    await browser
      .getByRole('row', { name: /Example 1/ })
      .getByRole('button', { name: 'Reference', exact: true })
      .click();
    await setup.getByLabel('Selection name', { exact: true }).fill('R1');
    const atom = setup.getByRole('button', { name: 'Atom 0 (C)', exact: true });
    await expect(atom).toBeEnabled();
    await atom.click();
    await setup.getByRole('button', { name: 'Save region', exact: true }).click();
    await expect(
      setup.getByText('Region saved · 1 attachment points', { exact: true }),
    ).toBeVisible();
    await setup.getByRole('button', { name: 'Run full study', exact: true }).click();
    const job = await persisted(page, 'job');
    expect(job.kind).toBe('study');
    const report = page.getByRole('region', { name: 'Study report', exact: true });
    await expect(report.getByRole('navigation', { name: 'Study views', exact: true })).toBeVisible({
      timeout: 30000,
    });
    for (const tab of [
      'Overview',
      'Scaffolds',
      'Leads',
      'Variable regions',
      'Fragment summary',
      'Activity table',
    ]) {
      await report.getByRole('button', { name: tab, exact: true }).click();
      const view = report.getByRole('region', { name: tab, exact: true });
      await expect(view).toBeVisible();
      if (tab === 'Activity table') await expect(view.locator('tbody tr')).toHaveCount(5);
      const contained = await view.locator('.sar-composition-donut').evaluateAll((figures) =>
        figures.every((figure) => {
          const caption = figure.querySelector('figcaption')?.getBoundingClientRect();
          return caption && caption.bottom <= figure.getBoundingClientRect().bottom + 1;
        }),
      );
      expect(contained).toBe(true);
      // Capture rendered structures, never a transient loading placeholder.
      await expect
        .poll(
          () =>
            view.locator('.sar-study-image, .sar-reference-map-image').evaluateAll((figures) =>
              figures.every((figure) => {
                const image = figure.querySelector('img');
                return image?.complete && image.naturalWidth > 0;
              }),
            ),
          { timeout: 20000 },
        )
        .toBe(true);
      expect(
        await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth + 1),
      ).toBe(true);
      const maps = await view.locator('.sar-reference-map-image').evaluateAll((items) =>
        items.every((item) => {
          const picture = item.querySelector('img')?.getBoundingClientRect();
          const marks = item.querySelector('.sar-region-map')?.getBoundingClientRect();
          return (
            picture &&
            marks &&
            ['x', 'y', 'width', 'height'].every(
              (key) =>
                Math.abs(
                  (picture[key as keyof DOMRect] as number) -
                    (marks[key as keyof DOMRect] as number),
                ) < 1,
            )
          );
        }),
      );
      expect(maps).toBe(true);
      await page.screenshot({
        path: test.info().outputPath(`study-${width}-${tab.replaceAll(' ', '-')}.png`),
        fullPage: true,
      });
    }
    await report.getByRole('button', { name: 'Variable regions', exact: true }).click();
    const regions = report.getByRole('region', { name: 'Variable regions', exact: true });
    // Fragment1 includes an unchanged blank reading. Inspect the actual ethyl
    // transformation for the numeric-difference contract.
    await regions
      .locator('.sar-fragment-strip article')
      .filter({ has: page.getByRole('heading', { name: 'Fragment 2', exact: true }) })
      .getByRole('button', { name: 'Preview modification', exact: true })
      .click();
    const preview = regions.getByRole('region', { name: 'Transformation preview', exact: true });
    await expect(
      preview.getByRole('combobox', { name: 'Modified compound', exact: true }),
    ).toBeEnabled();
    await expect(preview.locator('.sar-molecule-comparison img')).toHaveCount(2);
    await expect
      .poll(() =>
        preview
          .locator('img')
          .evaluateAll((images) =>
            images.every(
              (image) =>
                (image as HTMLImageElement).complete &&
                (image as HTMLImageElement).naturalWidth > 0,
            ),
          ),
      )
      .toBe(true);
    await expect(preview).toContainText('Δ -9.00');
    await page.screenshot({ path: test.info().outputPath(`preview-${width}.png`), fullPage: true });
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth + 1)).toBe(
      true,
    );
    await report.getByRole('button', { name: 'Activity table', exact: true }).click();
    const table = report.getByRole('region', { name: 'Activity table', exact: true });
    await expect(table.getByRole('rowheader', { name: 'Example 5', exact: true })).toBeVisible();
    const complete = await page.request.get(
      `/api/v1/sar/jobs/${job.id}/study/rows?query=Example+5`,
    );
    expect(complete.status()).toBe(200);
    const noActivity = (await complete.json()).items[0];
    expect(noActivity.properties.molecular_weight).toBeGreaterThan(0);
    expect(noActivity.prediction_origin).toBe('not_provided');
    const downloading = page.waitForEvent('download');
    await report.getByRole('button', { name: 'Export report JSON', exact: true }).click();
    const download = await downloading;
    const exported = JSON.parse(await readFile((await download.path())!, 'utf8'));
    expect(exported.report.rows).toHaveLength(5);
    expect(exported.input.molecules).toHaveLength(5);
    expect(exported.report.article_algorithm_reproduced).toBe(false);
    expect(exported.report.regions).toHaveLength(1);
    await page
      .getByRole('combobox', { name: 'Interface language', exact: true })
      .selectOption('zh-CN');
    await expect(
      page
        .getByRole('region', { name: '研究报告', exact: true })
        .getByRole('rowheader', { name: 'Example 5', exact: true }),
    ).toBeVisible();
    await page.getByRole('combobox', { name: '界面语言', exact: true }).selectOption('en');
    await page.reload();
    await expect(
      page
        .getByRole('region', { name: 'Study report', exact: true })
        .getByRole('navigation', { name: 'Study views', exact: true }),
    ).toBeVisible();
    expect(errors).toEqual([]);
    expect(foreignWrites).toEqual([]);
  });
}
