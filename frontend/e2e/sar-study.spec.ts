import { expect, test } from '@playwright/test';
import type { Page } from '@playwright/test';
import { readFile } from 'node:fs/promises';
import { checkStudyTableControls } from './sar-table-actions';

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
    page.on('console', async (message) => {
      if (message.text().startsWith('reference_visibility_geometry')) {
        console.log('reference_visibility_geometry', await message.args()[1]?.jsonValue());
      }
    });
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
      ...['0.01', '0.02', '0.03', '0.04', '0.05', '0.06', '1', '9', '10', '99', '100'].map(
        (value, index) =>
          `Example ${index + 6},${'C'.repeat(index + 4)}Oc1ccc(Cl)cc1,${value},T,binding,not applicable,1h`,
      ),
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
    expect(dataset.row_count).toBe(16);
    const setup = page.getByRole('region', { name: 'Study setup', exact: true });
    await expect(setup).toBeVisible();
    await expect(
      setup.getByRole('group', { name: 'Choose activity measurements · 0/1', exact: true }),
    ).toBeVisible();
    await setup.getByRole('checkbox', { name: /IC50/ }).check();
    const selectedLabel = await setup.locator('.sar-context-choice strong').first().innerText();
    await expect(setup.getByText('Confirm direction; source grades must be unique.')).toHaveCount(
      0,
    );
    await setup
      .getByRole('combobox', { name: 'Activity direction', exact: true })
      .selectOption('lower');
    await expect(
      setup.getByText('Concentration potency uses the tenth strongest measurement’s decade.'),
    ).toBeVisible();
    await setup.getByRole('button', { name: 'Continue', exact: true }).click();
    await expect(setup.locator('.sar-selected-contexts li')).toHaveText(selectedLabel);
    await setup.getByText('Add a named selection', { exact: true }).click();
    const browser = setup.getByRole('region', { name: 'Choose reference molecule', exact: true });
    await browser
      .getByRole('row')
      .filter({ has: page.getByRole('rowheader', { name: 'Example 1', exact: true }) })
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
    await browser
      .getByRole('row')
      .filter({ has: page.getByRole('rowheader', { name: 'Example 2', exact: true }) })
      .getByRole('button', { name: 'Reference', exact: true })
      .click();
    await setup.getByLabel('Selection name', { exact: true }).fill('R2');
    const halogen = setup.getByRole('button', { name: /^Atom \d+ \(Cl\)$/ });
    await expect(halogen).toHaveCount(1);
    await expect(halogen).toBeEnabled();
    await halogen.click();
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
    const details = report.getByRole('button', { name: 'Details', exact: true });
    await expect(report.locator('.sar-study-header')).toContainText('Complete');
    await expect(report.locator('.sar-study-header')).toContainText('Research preview');
    await details.click();
    await expect(page.getByRole('dialog', { name: 'Details', exact: true })).toBeVisible();
    await page.keyboard.press('Escape');
    await expect(page.getByRole('dialog')).toHaveCount(0);
    await expect(details).toBeFocused();
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
      const singleRow = await report.locator('.sar-study-tabs').evaluate((strip) => {
        const buttons = Array.from(strip.querySelectorAll('button'));
        const active = strip.querySelector('[aria-current]')!.getBoundingClientRect();
        const bounds = strip.getBoundingClientRect();
        return {
          oneRow: buttons.every(
            (button) =>
              Math.abs(
                button.getBoundingClientRect().top - buttons[0]!.getBoundingClientRect().top,
              ) < 1,
          ),
          currentVisible: active.left >= bounds.left - 1 && active.right <= bounds.right + 1,
          height: bounds.height,
        };
      });
      expect(singleRow.oneRow).toBe(true);
      expect(singleRow.currentVisible).toBe(true);
      expect(singleRow.height).toBeLessThanOrEqual(82);
      if (['Overview', 'Scaffolds', 'Variable regions', 'Fragment summary'].includes(tab))
        await expect(view.locator('.sar-policy-note').first()).toContainText(
          'Strong <10 nM; medium 10 nM–<100 nM; weak ≥100 nM',
        );
      if (['Overview', 'Variable regions', 'Fragment summary'].includes(tab)) {
        const rule = view.locator('.sar-policy-note').first();
        const disclosure = view
          .locator(
            tab === 'Overview' ? '.sar-context-detail summary' : '.sar-region-method summary',
          )
          .first();
        await expect(rule).toBeHidden();
        await disclosure.click();
        await expect(rule).toBeVisible();
        await disclosure.click();
        await expect(rule).toBeHidden();
      }
      if (tab === 'Activity table') {
        await expect(view.locator('tbody tr')).toHaveCount(16);
        await checkStudyTableControls(page, report, width);
      }
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
                return (
                  image?.complete &&
                  image.naturalWidth > 0 &&
                  !figure.querySelector('.feedback.loading')
                );
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
      if (tab === 'Variable regions' || tab === 'Fragment summary') {
        const outcomes = view.locator('.sar-fragment-comparisons');
        await expect(outcomes.first()).toBeVisible();
        expect(await outcomes.first().locator('dd').count()).toBe(4);
        const fragments = await view.locator('.sar-fragment-strip article').evaluateAll((cards) =>
          cards.map((card) => {
            const stack = card.querySelector('.sar-composition-stack')!;
            const svg = decodeURIComponent(
              card.querySelector('img')!.src.split(',').slice(1).join(','),
            );
            return {
              height: stack.getBoundingClientRect().height,
              direction: getComputedStyle(stack).flexDirection,
              canvas: new DOMParser()
                .parseFromString(svg, 'image/svg+xml')
                .documentElement.getAttribute('viewBox'),
            };
          }),
        );
        expect(fragments.length).toBeGreaterThan(0);
        for (const fragment of fragments) {
          expect(fragment.height).toBeLessThanOrEqual(14);
          expect(fragment.direction).toBe('row');
          expect(fragment.canvas).toBe('0 0 360 240');
        }
      }
      if (tab === 'Leads') {
        // The strongest candidate can contain Br rather than Cl. Check the
        // actual candidate gallery, without forcing its scientific ordering.
        const sources = await view
          .locator('.sar-study-image img')
          .evaluateAll((images) => images.map((image) => image.getAttribute('src')!));
        const svg = sources
          .map((displayed) => decodeURIComponent(displayed.split(',').slice(1).join(',')))
          .join('\n');
        expect(svg).toContain('#B42318');
        expect(svg).toContain('#166534');
        expect(svg).not.toContain('#FF0000');
        expect(svg).not.toContain('#00CC00');
      }
      await page.screenshot({
        path: test.info().outputPath(`study-${width}-${tab.replaceAll(' ', '-')}.png`),
        fullPage: true,
      });
    }
    // A card-to-table callback is a programmatic selection, not a nav click.
    await report.getByRole('button', { name: 'Scaffolds', exact: true }).click();
    await report
      .getByRole('region', { name: 'Scaffolds', exact: true })
      .getByRole('button', { name: 'View molecules', exact: true })
      .first()
      .click();
    await expect(report.getByRole('region', { name: 'Activity table', exact: true })).toBeVisible();
    await expect
      .poll(() =>
        report.locator('.sar-study-tabs').evaluate((strip) => {
          const active = strip.querySelector('[aria-current]')!.getBoundingClientRect(),
            bounds = strip.getBoundingClientRect();
          return active.left >= bounds.left - 1 && active.right <= bounds.right + 1;
        }),
      )
      .toBe(true);
    await report.getByRole('button', { name: 'Variable regions', exact: true }).click();
    const regions = report.getByRole('region', { name: 'Variable regions', exact: true });
    const atomTarget = regions.locator('.sar-region-hotspots button').first();
    expect(await atomTarget.evaluate((element) => getComputedStyle(element).borderTopColor)).toBe(
      'rgba(0, 0, 0, 0)',
    );
    await atomTarget.click();
    const hoverStyle = await atomTarget.evaluate((element) => {
      const style = getComputedStyle(element);
      return { background: style.backgroundColor, border: style.borderTopWidth };
    });
    expect(hoverStyle.background).toBe('rgba(0, 0, 0, 0)');
    expect(hoverStyle.border).toBe('2px');
    // Fragment1 includes an unchanged blank reading. Inspect the actual ethyl
    // transformation for the numeric-difference contract.
    const previewTrigger = regions
      .locator('.sar-fragment-strip article')
      .filter({ has: page.getByRole('heading', { name: 'Fragment 2', exact: true }) })
      .getByRole('button', { name: 'Preview modification', exact: true });
    await previewTrigger.click();
    const preview = regions.getByRole('region', { name: 'Transformation preview', exact: true });
    await expect(preview).toBeFocused();
    await expect
      .poll(() =>
        preview.evaluate((element) => {
          const bounds = element.getBoundingClientRect();
          return bounds.top >= -1 && bounds.top < innerHeight / 2;
        }),
      )
      .toBe(true);
    const map = regions.locator('.sar-region-map');
    await expect(map.locator('g[data-selected="true"]')).toHaveCount(1);
    expect(
      await regions
        .locator('.sar-region-hotspots button')
        .evaluateAll((buttons) =>
          buttons.every((button) => (button as HTMLButtonElement).tabIndex === -1),
        ),
    ).toBe(true);
    await preview
      .getByRole('button', { name: 'Close transformation preview', exact: true })
      .click();
    await expect(preview).toHaveCount(0);
    await expect(previewTrigger).toBeFocused();
    await previewTrigger.click();
    await expect(preview).toBeFocused();
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
    if (width > 1000) {
      const referencePane = regions.getByRole('region', {
        name: 'Reference structures',
        exact: true,
      });
      await expect(referencePane.locator('.sar-reference-map-card')).toHaveCount(2);
      await expect(referencePane).toHaveAttribute('tabindex', '0');
      const jointView = () =>
        referencePane.evaluate((pane) => {
          const image = pane.querySelector('img')!.getBoundingClientRect();
          const bounds = pane.getBoundingClientRect();
          const comparison = document.querySelector('.sar-transformation')!.getBoundingClientRect();
          if (image.top < 0 || image.bottom > innerHeight)
            console.log('reference_visibility_geometry', {
              pane: bounds.toJSON(),
              image: image.toJSON(),
              comparison: comparison.toJSON(),
              scrollTop: pane.scrollTop,
              viewportHeight: innerHeight,
            });
          return {
            imageVisible: image.top >= 0 && image.bottom <= innerHeight,
            sideBySide: bounds.right < comparison.left,
            position: getComputedStyle(pane).position,
            maxHeight: bounds.height <= innerHeight - 84,
          };
        });
      await expect.poll(jointView).toEqual({
        imageVisible: true,
        sideBySide: true,
        position: 'sticky',
        maxHeight: true,
      });
      await referencePane.focus();
      const scroll = await referencePane.evaluate((element) => element.scrollTop);
      await page.keyboard.press('ArrowDown');
      await expect
        .poll(() => referencePane.evaluate((element) => element.scrollTop))
        .toBeGreaterThan(scroll);
      await page.keyboard.press('Home');
      await expect
        .poll(() => referencePane.evaluate((element) => element.scrollTop))
        .toBeLessThanOrEqual(1);
    }
    // Inspect only this published, loaded source drawing: no new engine/read/write.
    const originalImage = preview.locator('.sar-molecule-comparison img').first();
    const sourceLabel = (await originalImage.getAttribute('alt'))!;
    const sourceDrawing = await originalImage.getAttribute('src');
    const enlarge = preview.getByRole('button', {
      name: `Enlarge structure ${sourceLabel}`,
      exact: true,
    });
    const drawingRequests: string[] = [];
    const observeDrawing = (request: import('@playwright/test').Request) => {
      if (request.url().includes('/api/v1/sar/') && request.url().includes('/drawing'))
        drawingRequests.push(request.url());
    };
    page.on('request', observeDrawing);
    await enlarge.click();
    const focus = page.getByRole('dialog', {
      name: `Molecular preview · ${sourceLabel}`,
      exact: true,
    });
    await expect(focus).toBeVisible();
    await expect(focus.getByRole('img', { name: sourceLabel, exact: true })).toHaveAttribute(
      'src',
      sourceDrawing!,
    );
    await expect(focus.getByLabel('Magnification relative to fit', { exact: true })).toHaveText(
      '100%',
    );
    async function fittedImageIsContained() {
      return focus.locator('.sar-molecule-focus-viewport').evaluate((pane) => {
        const image = pane.querySelector('img')!.getBoundingClientRect();
        const bounds = pane.getBoundingClientRect();
        return (
          image.left >= bounds.left - 1 &&
          image.top >= bounds.top - 1 &&
          image.right <= bounds.left + pane.clientWidth + 1 &&
          image.bottom <= bounds.top + pane.clientHeight + 1
        );
      });
    }
    expect(await fittedImageIsContained()).toBe(true);
    await focus.screenshot({ path: test.info().outputPath(`molecular-fit-${width}.png`) });
    for (let i = 0; i < 3; i++)
      await focus.getByRole('button', { name: 'Zoom in structure', exact: true }).click();
    await expect(focus.getByLabel('Magnification relative to fit', { exact: true })).toHaveText(
      '175%',
    );
    const pane = focus.getByRole('region', { name: 'Molecular canvas', exact: true });
    const geometry = await pane.evaluate((element) => ({
      pane: element.clientWidth,
      canvas: element.firstElementChild!.getBoundingClientRect().width,
    }));
    expect(Math.abs(geometry.canvas - geometry.pane * 1.75)).toBeLessThan(1);
    await focus.getByRole('button', { name: 'Zoom in structure', exact: true }).focus();
    await page.keyboard.press('Tab');
    await expect(focus.getByRole('button', { name: 'Fit', exact: true })).toBeFocused();
    await page.keyboard.press('Tab');
    await expect(pane).toBeFocused();
    const scroll = await pane.evaluate((element) => element.scrollLeft);
    await page.keyboard.press('ArrowRight');
    await expect.poll(() => pane.evaluate((element) => element.scrollLeft)).toBeGreaterThan(scroll);
    await focus.getByRole('button', { name: 'Fit', exact: true }).click();
    await expect
      .poll(() => pane.evaluate((element) => element.scrollLeft + element.scrollTop))
      .toBe(0);
    expect(await fittedImageIsContained()).toBe(true);
    expect(
      await focus.evaluate((element) => element.getBoundingClientRect().right <= innerWidth),
    ).toBe(true);
    await page.keyboard.press('Escape');
    await expect(focus).toHaveCount(0);
    await expect(enlarge).toBeFocused();
    await page
      .getByRole('combobox', { name: 'Interface language', exact: true })
      .selectOption('zh-CN');
    const chinesePreview = page.getByRole('region', { name: '改造预览', exact: true });
    const chineseEnlarge = chinesePreview.getByRole('button', {
      name: `放大结构 ${sourceLabel}`,
      exact: true,
    });
    await chineseEnlarge.click();
    const translatedFocus = page.getByRole('dialog', {
      name: `结构预览 · ${sourceLabel}`,
      exact: true,
    });
    await expect(
      translatedFocus.getByRole('img', { name: sourceLabel, exact: true }),
    ).toHaveAttribute('src', sourceDrawing!);
    await page.keyboard.press('Escape');
    await expect(chineseEnlarge).toBeFocused();
    await page.getByRole('combobox', { name: '界面语言', exact: true }).selectOption('en');
    expect(drawingRequests).toEqual([]);
    page.off('request', observeDrawing);
    if (width === 390) {
      const changeFits = await preview
        .locator('.sar-preview-change')
        .first()
        .evaluate((cell) => {
          const bounds = cell.getBoundingClientRect();
          const clip = cell.closest('.sar-table-scroll')!.getBoundingClientRect();
          return bounds.left >= clip.left - 1 && bounds.right <= clip.right + 1;
        });
      expect(changeFits).toBe(true);
    }
    // Check the actual Chromium accessibility tree after responsive CSS, not
    // only inferred DOM roles. Native headers must still belong to the table.
    const protocol = await page.context().newCDPSession(page);
    const accessibility = await protocol.send('Accessibility.getFullAXTree');
    const accessibleTable = accessibility.nodes.find(
      (node) =>
        !node.ignored && node.role?.value === 'table' && node.name?.value === 'Recorded activity',
    );
    expect(accessibleTable).toBeTruthy();
    const byId = new Map(accessibility.nodes.map((node) => [node.nodeId, node]));
    const descendants = new Set<string>();
    function visit(id: string) {
      if (descendants.has(id)) return;
      descendants.add(id);
      for (const child of byId.get(id)?.childIds ?? []) visit(child);
    }
    visit(accessibleTable!.nodeId);
    expect(
      accessibility.nodes.some(
        (node) =>
          descendants.has(node.nodeId) &&
          !node.ignored &&
          node.role?.value === 'columnheader' &&
          node.name?.value === 'Change',
      ),
    ).toBe(true);
    await protocol.detach();
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
    await report.getByLabel('Export format', { exact: true }).selectOption('json');
    await report.getByRole('button', { name: 'Export report JSON', exact: true }).click();
    const download = await downloading;
    const exported = JSON.parse(await readFile((await download.path())!, 'utf8'));
    expect(exported.report.rows).toHaveLength(16);
    expect(exported.input.molecules).toHaveLength(16);
    expect(exported.report.policies[0].strength_scale).toMatchObject({
      method: 'tenth_decade',
      anchor_rank: 10,
      strong_boundary: 10,
      medium_boundary: 100,
    });
    for (const [label, tier] of [
      ['Example 13', 'strong'],
      ['Example 14', 'medium'],
      ['Example 15', 'medium'],
      ['Example 16', 'weak'],
    ] as const) {
      await expect(
        table
          .getByRole('row')
          .filter({ has: page.getByRole('rowheader', { name: label, exact: true }) })
          .locator('td[data-activity-strength]'),
      ).toHaveAttribute('data-activity-strength', tier);
    }
    expect(exported.report.article_algorithm_reproduced).toBe(false);
    expect(exported.report.regions).toHaveLength(2);
    expect(
      exported.report.regions.map(
        (summary: { reference_label: string }) => summary.reference_label,
      ),
    ).toEqual(['Example 1', 'Example 2']);
    await page
      .getByRole('combobox', { name: 'Interface language', exact: true })
      .selectOption('zh-CN');
    await expect(
      page
        .getByRole('region', { name: '研究报告', exact: true })
        .getByRole('rowheader', { name: 'Example 5', exact: true }),
    ).toBeVisible();
    await expect(page.getByRole('button', { name: '筛选与排序', exact: true })).toHaveAttribute(
      'aria-expanded',
      'false',
    );
    await page.getByRole('combobox', { name: '界面语言', exact: true }).selectOption('en');
    await page.reload();
    await expect(
      page
        .getByRole('region', { name: 'Study report', exact: true })
        .getByRole('navigation', { name: 'Study views', exact: true }),
    ).toBeVisible();
    expect(errors).toEqual([]);
    await page.evaluate(() => {
      location.hash = location.hash.replace(/&job=[a-f0-9]{32}/, '');
    });
    const returning = page.getByRole('region', { name: 'Study setup', exact: true });
    await expect(
      returning.getByRole('list', { name: 'Analysis steps', exact: true }),
    ).toBeVisible();
    await expect(returning.getByRole('button', { name: 'Continue', exact: true })).toBeDisabled();
    expect(foreignWrites).toEqual([]);
  });
}
