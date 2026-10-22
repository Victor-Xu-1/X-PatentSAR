import { expect, test } from '@playwright/test';
import type { Locator } from '@playwright/test';

async function expectShortLabel(th: Locator, state: string) {
  const measured = await th.locator('.column-heading > span').evaluate((label) => {
    const range = document.createRange();
    range.selectNodeContents(label);
    return {
      label: label.textContent,
      lines: new Set([...range.getClientRects()].map((rect) => Math.round(rect.y))).size,
    };
  });
  expect.soft(measured.lines, `${state}: ${measured.label} must not split`).toBe(1);
}

// Existing original records only. No extraction, correction, export or analysis.
for (const width of [390, 1672]) {
  test(`source heading remains readable through locale and resize at ${width}px`, async ({
    page,
  }) => {
    const project = process.env.PATENTSAR_E2E_SOURCE_PROJECT_ID;
    expect(project).toBeTruthy();
    const writes: string[] = [],
      errors: string[] = [];
    page.on('pageerror', (error) => errors.push(error.message));
    await page.route('**/api/v1/**', (route) => {
      if (route.request().method() === 'GET') return route.continue();
      writes.push(route.request().url());
      return route.abort();
    });
    await page.setViewportSize({ width, height: 1060 });
    await page.goto('/#/projects/' + project);
    await expect(page.locator('.results-table tbody tr[data-compound]').first()).toBeVisible();
    for (const language of ['en', 'zh-CN']) {
      const chooser = page.getByRole('combobox', { name: /^(Interface language|界面语言)$/ });
      await chooser.ariaSnapshot();
      await chooser.selectOption(language);
      const label = language === 'en' ? 'Original' : '原文';
      const header = page.locator('.results-table th[data-column="source"]');
      await expect(header.locator('.column-heading > span')).toHaveText(label);
      await header.ariaSnapshot();
      await header.scrollIntoViewIfNeeded();
      await expectShortLabel(header, `${language} default`);
      const resize = header.getByRole('slider', {
        name: language === 'en' ? 'Resize Original column' : '调整原文列宽',
        exact: true,
      });
      await resize.focus();
      await resize.press('Home');
      await expect(resize).toHaveValue((await resize.getAttribute('min'))!);
      await expectShortLabel(header, `${language} minimum`);
      await page.screenshot({
        path: test.info().outputPath(`source-min-${width}-${language}.png`),
      });
      await header.ariaSnapshot();
      await resize.press('End');
      await expect(resize).toHaveValue((await resize.getAttribute('max'))!);
      await expectShortLabel(header, `${language} expanded`);
      await header.ariaSnapshot();
      await resize.dblclick();
      await expectShortLabel(header, `${language} reset`);
    }
    expect(writes).toEqual([]);
    expect(errors).toEqual([]);
  });
}
