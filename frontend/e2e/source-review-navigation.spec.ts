import { expect, test } from '@playwright/test';
import type { Locator } from '@playwright/test';

async function inViewport(control: Locator) {
  await expect(control).toBeInViewport({ ratio: 1 });
  await expect(control).toBeVisible();
}

async function disjointPanes(source: Locator, results: Locator) {
  const pdf = await source.locator('.pdf-pane').boundingBox();
  const table = await results.locator('.results-pane').boundingBox();
  const wrapper = await results.boundingBox();
  expect(pdf).not.toBeNull();
  expect(table).not.toBeNull();
  expect(wrapper).not.toBeNull();
  expect(table!.height).toBeLessThanOrEqual(wrapper!.height + 1);
  expect(table!.y + table!.height).toBeLessThanOrEqual(pdf!.y - 10);
}

const labels = {
  en: {
    view: 'View original',
    back: 'Back to results',
    expand: 'Expand original',
    collapse: 'Collapse original; results use full width',
    full: 'Fullscreen workspace',
    source: 'Original pane',
    results: 'Results pane',
    page: 'Original document page',
    resize: 'Resize original and results panes',
  },
  'zh-CN': {
    view: '查看原文',
    back: '返回结果',
    expand: '展开原文',
    collapse: '收起原文，结果全宽',
    full: '全屏工作区',
    source: '原文区域',
    results: '结果区域',
    page: '原始文档页码',
    resize: '调整原文与结果宽度',
  },
};

for (const width of [390, 800, 1672]) {
  for (const locale of ['en', 'zh-CN'] as const) {
    test(`original review, return and fullscreen preserve source at ${width}px ${locale}`, async ({
      page,
    }) => {
      const project = process.env.PATENTSAR_E2E_SOURCE_PROJECT_ID;
      expect(project, 'Requires the isolated controller-owned original source').toBeTruthy();
      const errors: string[] = [],
        writes: string[] = [],
        external: string[] = [];
      const origin = new URL(test.info().project.use.baseURL!).origin;
      page.on('pageerror', (error) => errors.push(error.message));
      await page.route('**/*', async (route) => {
        const request = route.request(),
          url = new URL(request.url());
        if (url.protocol !== 'http:' && url.protocol !== 'https:') return route.continue();
        if (url.origin !== origin) {
          external.push(url.origin);
          return route.abort();
        }
        const chemistryRead =
          request.method() === 'POST' && url.pathname === '/api/v1/chemistry/structure';
        if (url.pathname.startsWith('/api/v1/') && request.method() !== 'GET' && !chemistryRead) {
          writes.push(url.pathname);
          return route.abort();
        }
        await route.continue();
      });
      await page.setViewportSize({ width, height: 1060 });
      await page.goto(`/#/projects/${project}?page=1&tab=original&pdfWidth=31&pdf=0&fullscreen=0`);
      if (locale === 'zh-CN')
        await page
          .getByRole('combobox', { name: 'Interface language', exact: true })
          .selectOption(locale);
      const copy = labels[locale];
      const source = page.getByRole('region', { name: copy.source, exact: true });
      const results = page.getByRole('region', { name: copy.results, exact: true });
      const row = results.locator('.results-table tbody tr').first();
      await expect(row).toBeVisible();
      const identity = await row.locator('.frozen-compound').innerText();
      await expect(source).toHaveCount(0);
      await page.reload();
      await expect(source).toHaveCount(0);
      await page
        .getByRole('button', { name: width < 900 ? copy.view : copy.expand, exact: true })
        .click();
      await expect(source).toBeVisible();
      await expect(page.getByRole('textbox', { name: copy.page, exact: true })).toHaveValue('1');
      if (width < 900) {
        await expect(source).toBeFocused();
        await inViewport(source.locator('.pdf-toolbar'));
        await disjointPanes(source, results);
        const input = page.getByRole('textbox', { name: copy.page, exact: true });
        await input.fill('2');
        const sourceUrl = page.url();
        await source.getByRole('button', { name: copy.back, exact: true }).click();
        await expect(results).toBeFocused();
        await inViewport(results.locator('.result-toolbar'));
        await page.getByRole('button', { name: copy.view, exact: true }).focus();
        await page.keyboard.press('Enter');
        await expect(source).toBeFocused();
        await expect(input).toHaveValue('2');
        expect(page.url()).toBe(sourceUrl);
        await source.getByRole('button', { name: copy.back, exact: true }).click();
      } else {
        await expect(page.getByRole('button', { name: copy.view, exact: true })).toHaveCount(0);
        await expect(page.getByRole('button', { name: copy.back, exact: true })).toHaveCount(0);
        const slider = page.getByRole('slider', { name: copy.resize, exact: true });
        await expect(slider).toHaveAttribute('aria-valuenow', '31');
        await slider.focus();
        await page.keyboard.press('ArrowRight');
        await expect(slider).toHaveAttribute('aria-valuenow', '33');
        await page.getByRole('button', { name: copy.collapse, exact: true }).click();
      }
      await row
        .getByRole('button', { name: /structure source page \d+|结构来源第 \d+ 页/ })
        .click();
      await expect(source.locator('.annotation-box.selected')).toBeInViewport();
      expect(await row.locator('.frozen-compound').innerText()).toBe(identity);
      const selectedSource = page.url();
      await page.reload();
      await expect(source.locator('.annotation-box.selected')).toBeInViewport();
      expect(page.url()).toBe(selectedSource);
      const fullscreen = page.getByRole('button', { name: copy.full, exact: true });
      await fullscreen.scrollIntoViewIfNeeded();
      await fullscreen.click();
      await expect(page.locator('.workspace-layout')).toHaveClass(/is-fullscreen/);
      if (width < 900) {
        await page.getByRole('button', { name: copy.view, exact: true }).click();
        await expect(source).toBeFocused();
        await inViewport(source.locator('.pdf-toolbar'));
        await disjointPanes(source, results);
        await page.screenshot({ path: test.info().outputPath('source-fullscreen.png') });
        await source.getByRole('button', { name: copy.back, exact: true }).click();
        await expect(results).toBeFocused();
        await inViewport(results.locator('.result-toolbar'));
      } else {
        await expect(page.getByRole('slider', { name: copy.resize, exact: true })).toHaveAttribute(
          'aria-valuenow',
          '33',
        );
        const pdf = await source.boundingBox(),
          table = await results.boundingBox();
        expect(pdf!.x + pdf!.width).toBeLessThan(table!.x);
      }
      await page.screenshot({ path: test.info().outputPath('results-fullscreen.png') });
      await page.keyboard.press('Escape');
      await expect(page.locator('.workspace-layout')).not.toHaveClass(/is-fullscreen/);
      await expect(fullscreen).toBeFocused();
      expect(new URLSearchParams(new URL(page.url()).hash.split('?')[1]).get('fullscreen')).toBe(
        '0',
      );
      expect(page.url()).toBe(selectedSource);
      await expect(source.locator('.annotation-box.selected')).toHaveCount(1);
      expect(
        await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth + 1),
      ).toBe(true);
      expect(errors).toEqual([]);
      expect(writes).toEqual([]);
      expect(external).toEqual([]);
    });
  }
}
