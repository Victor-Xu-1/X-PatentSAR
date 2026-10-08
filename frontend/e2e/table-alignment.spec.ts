import { expect, test } from '@playwright/test';
import type { Locator } from '@playwright/test';

const projectId = process.env.PATENTSAR_E2E_SOURCE_PROJECT_ID;

async function expectReadableMetricHeadings(table: Locator) {
  const metricHeadings = await table.locator('th.prediction-column').evaluateAll((headers) =>
    headers.map((header) => {
      const heading = header.querySelector('.column-heading') as HTMLElement;
      const label = heading.querySelector('span')!;
      const style = getComputedStyle(heading);
      const bounds = heading.getBoundingClientRect();
      const menu = header.querySelector('.column-menu-button')!.getBoundingClientRect();
      const context = document.createElement('canvas').getContext('2d')!;
      context.font = style.font;
      const textWidth = context.measureText(label.textContent!).width;
      return {
        whiteSpace: style.whiteSpace,
        fits:
          textWidth <=
          bounds.width - parseFloat(style.paddingLeft) - parseFloat(style.paddingRight) + 0.5,
        menuGap: menu.left - (bounds.left + bounds.width / 2 + textWidth / 2),
      };
    }),
  );
  expect(metricHeadings).toHaveLength(6);
  for (const heading of metricHeadings) {
    expect(heading.whiteSpace).toBe('nowrap');
    expect(heading.fits).toBe(true);
    expect(heading.menuGap).toBeGreaterThanOrEqual(1);
  }
}

for (const width of [1830, 390]) {
  test(`six short metric headers remain readable before or after results at ${width}`, async ({
    page,
  }) => {
    test.skip(!projectId, 'Requires an approved original project; read-only');
    await page.setViewportSize({ width, height: width === 1830 ? 1050 : 844 });
    await page.goto(`/#/projects/${projectId}?tab=original&pdfWidth=28`);
    const table = page.getByRole('table');
    await expect(table).toBeVisible();
    await expectReadableMetricHeadings(table);
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth + 2)).toBe(
      true,
    );
  });
  for (const density of ['compact', 'comfortable'] as const) {
    test(`real result table has centered content and functional header menus at ${width} in ${density}`, async ({
      page,
    }) => {
      test.skip(
        !projectId,
        'Requires an integrated candidate and approved original project; read-only',
      );
      await page.setViewportSize({ width, height: width === 1830 ? 1050 : 844 });
      const errors: string[] = [];
      page.on('pageerror', (error) => errors.push(error.message));
      await page.goto(`/#/projects/${projectId}?tab=original&pdfWidth=28`);
      const table = page.getByRole('table');
      await expect(table).toBeVisible();
      await expect(table.locator('tbody tr[data-compound]').first()).toBeVisible();
      if (density === 'comfortable') {
        await page.getByRole('button', { name: '列表选项', exact: true }).click();
        await page.getByText('显示选项', { exact: true }).click();
        await page.getByRole('button', { name: '舒适视图', exact: true }).click();
        await page.keyboard.press('Escape');
      }
      await expect(table).toHaveAttribute('data-density', density);
      const cells = await table.locator('th, td').evaluateAll((elements) =>
        elements.map((element) => {
          const style = getComputedStyle(element);
          return { horizontal: style.textAlign, vertical: style.verticalAlign };
        }),
      );
      for (const cell of cells) expect(cell).toEqual({ horizontal: 'center', vertical: 'middle' });
      await expect(table.getByRole('columnheader', { name: '#', exact: true })).toHaveCount(0);
      const headings = await table.locator('.column-heading').evaluateAll((elements) =>
        elements.map((element) => {
          const heading = element.getBoundingClientRect();
          const header = element.closest('th')!.getBoundingClientRect();
          return Math.abs(heading.x + heading.width / 2 - header.x - header.width / 2);
        }),
      );
      for (const offset of headings) expect(offset).toBeLessThanOrEqual(1);
      // Short scientific labels (especially TPSA) must fit beside their menus
      // at the default width, rather than splitting an acronym across lines.
      await expectReadableMetricHeadings(table);
      const observations = await table.locator('.activity-observation').evaluateAll((elements) =>
        elements.map((element) => {
          const style = getComputedStyle(element);
          return [style.alignItems, style.justifyContent];
        }),
      );
      for (const alignment of observations) expect(alignment).toEqual(['center', 'center']);
      const contents = await table.locator('tbody td').evaluateAll((elements) =>
        elements.map((element) => {
          const content = element.firstElementChild!.getBoundingClientRect();
          const cell = element.getBoundingClientRect();
          return {
            horizontal: Math.abs(content.x + content.width / 2 - cell.x - cell.width / 2),
            vertical: Math.abs(content.y + content.height / 2 - cell.y - cell.height / 2),
          };
        }),
      );
      for (const content of contents) {
        expect(content.horizontal).toBeLessThanOrEqual(1);
        expect(content.vertical).toBeLessThanOrEqual(1);
      }
      const icons = await table.locator('.column-menu-button').evaluateAll((elements) =>
        elements.map((element) => {
          const icon = element.querySelector('svg')!.getBoundingClientRect();
          const button = element.getBoundingClientRect();
          const header = element.closest('th')!.getBoundingClientRect();
          return [
            Math.abs(icon.x + icon.width / 2 - button.x - button.width / 2),
            Math.abs(icon.y + icon.height / 2 - button.y - button.height / 2),
            Math.abs(button.y + button.height / 2 - header.y - header.height / 2),
          ];
        }),
      );
      for (const offsets of icons)
        for (const offset of offsets) expect(offset).toBeLessThanOrEqual(1);
      const trigger = table.getByRole('button', { name: '原文编号 列选项', exact: true });
      const labelFits = await table.locator('th.frozen-compound').evaluate((header) => {
        const heading = header.querySelector('.column-heading') as HTMLElement;
        const button = header.querySelector('.column-menu-button')!;
        const style = getComputedStyle(heading);
        const canvas = document.createElement('canvas');
        const context = canvas.getContext('2d')!;
        context.font = style.font;
        const textWidth = context.measureText('原文编号').width;
        const bounds = heading.getBoundingClientRect();
        const menu = button.getBoundingClientRect();
        const available =
          bounds.width - parseFloat(style.paddingLeft) - parseFloat(style.paddingRight);
        return {
          fits: textWidth <= available + 0.5,
          gap: menu.left - (bounds.left + bounds.width / 2 + textWidth / 2),
        };
      });
      expect(labelFits.fits).toBe(true);
      expect(labelFits.gap).toBeGreaterThanOrEqual(1);
      await trigger.click();
      const menu = page.getByRole('dialog', { name: '原文编号 列选项', exact: true });
      await expect(menu).toBeVisible();
      await expect(trigger).toHaveAttribute('aria-controls', (await menu.getAttribute('id'))!);
      await expect(menu.getByRole('button', { name: '升序', exact: true })).toBeEnabled();
      await expect(menu.getByLabel('全选筛选取值', { exact: true })).toBeEnabled();
      await expect(menu.getByLabel('筛选方式', { exact: true })).toHaveCount(0);
      await menu.getByRole('button', { name: '文本筛选', exact: true }).click();
      await expect(menu.getByLabel('筛选方式', { exact: true })).toBeEnabled();
      await expect(menu.getByRole('button', { name: '确定', exact: true })).toBeEnabled();
      await page.keyboard.press('Escape');
      await expect(menu).toHaveCount(0);
      await expect(trigger).toBeFocused();

      const slider = table.getByRole('slider', { name: '调整原文编号列宽', exact: true });
      const previousWidth = Number(await slider.getAttribute('aria-valuenow'));
      await slider.focus();
      await page.keyboard.press('ArrowRight');
      await expect(slider).toHaveAttribute('aria-valuenow', String(previousWidth + 8));
      await page.keyboard.press('ArrowLeft');
      await expect(slider).toHaveAttribute('aria-valuenow', String(previousWidth));
      const scroll = page.locator('.table-scroll');
      await scroll.evaluate((element) => {
        element.scrollLeft = 300;
      });
      expect(
        await table
          .locator('th.frozen-compound')
          .evaluate((element) => getComputedStyle(element).position),
      ).toBe('sticky');
      expect(
        await table
          .locator('th.frozen-edit')
          .evaluate((element) => getComputedStyle(element).position),
      ).toBe('sticky');
      await scroll.evaluate((element) => {
        element.scrollLeft = 0;
      });
      await page.screenshot({
        path: test.info().outputPath(`table-alignment-${width}-${density}.png`),
        fullPage: true,
      });
      expect(errors).toEqual([]);
    });
  }
}
