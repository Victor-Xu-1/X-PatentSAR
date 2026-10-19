import { expect, test } from '@playwright/test';
import { decodeEnvironmentCatalog } from '../src/api/environmentDecoders';

const copy = {
  en: {
    language: 'Interface language',
    heading: 'Complete runtime environment',
    details: 'Environment details',
    components: 'Component details',
    runtime: 'Auxiliary text OCR runtime',
    model: 'Auxiliary text OCR model',
    unconfigured: 'No path is configured for this component.',
    missing: 'The configured path does not exist.',
  },
  'zh-CN': {
    language: '界面语言',
    heading: '完整运行环境',
    details: '环境详情',
    components: '组件详情',
    runtime: '辅助文字识别环境',
    model: '辅助文字识别模型',
    unconfigured: '未配置该组件路径。',
    missing: '配置路径不存在。',
  },
} as const;

for (const locale of ['en', 'zh-CN'] as const) {
  for (const width of [1672, 390]) {
    test(`optional ordinary text setup details stay lazy at ${locale}/${width}`, async ({
      page,
    }) => {
      const errors: string[] = [];
      const writes: string[] = [];
      page.on('pageerror', (error) => errors.push(error.message));
      page.on('request', (request) => {
        if (request.method() !== 'GET' && request.url().includes('/api/v1/environments'))
          writes.push(request.url());
      });
      await page.setViewportSize({ width, height: 942 });
      await page.goto('/#/settings');
      const language = page.getByRole('combobox', { name: 'Interface language', exact: true });
      if (locale === 'en') await expect(language).toHaveValue('en');
      else await language.selectOption(locale);
      await expect(
        page.getByRole('heading', { name: copy[locale].heading, exact: true }),
      ).toBeVisible();
      const response = await page.request.get('/api/v1/environments');
      expect(response.ok()).toBe(true);
      const catalog = decodeEnvironmentCatalog(await response.json());
      expect(catalog.components.map((component) => component.id)).toEqual(
        expect.arrayContaining(['text-ocr', 'text-ocr-models']),
      );
      await expect(page.locator('[data-component]')).toHaveCount(0);
      await page.getByRole('button', { name: copy[locale].details, exact: true }).click();
      const dialog = page.getByRole('dialog', { name: copy[locale].details, exact: true });
      await dialog.getByText(copy[locale].components, { exact: true }).click();
      for (const [id, name] of [
        ['text-ocr', copy[locale].runtime],
        ['text-ocr-models', copy[locale].model],
      ] as const) {
        const row = dialog.locator(`[data-component="${id}"]`);
        await row.scrollIntoViewIfNeeded();
        await expect(row.getByRole('heading', { name, exact: true })).toBeVisible();
        await expect(row).toContainText(
          catalog.components.find((component) => component.id === id)!.version,
        );
        const problem = catalog.components.find((component) => component.id === id)!.problem;
        if (problem === '未配置该组件路径。' || problem === '配置路径不存在。')
          await expect(row.locator('.component-problem').first()).toHaveText(
            problem === '未配置该组件路径。' ? copy[locale].unconfigured : copy[locale].missing,
          );
      }
      expect(await dialog.evaluate((node) => node.scrollWidth <= node.clientWidth + 2)).toBe(true);
      expect(
        await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth + 2),
      ).toBe(true);
      await page.screenshot({
        path: test.info().outputPath(`ordinary-text-${locale}-${width}.png`),
        fullPage: true,
      });
      await page.keyboard.press('Escape');
      await expect(dialog).toHaveCount(0);
      await expect(
        page.getByRole('button', { name: copy[locale].details, exact: true }),
      ).toBeFocused();
      await page.reload();
      await expect(
        page.getByRole('combobox', { name: copy[locale].language, exact: true }),
      ).toHaveValue(locale);
      await expect(
        page.getByRole('heading', { name: copy[locale].heading, exact: true }),
      ).toBeVisible();
      expect(writes).toEqual([]);
      expect(errors).toEqual([]);
    });
  }
}
