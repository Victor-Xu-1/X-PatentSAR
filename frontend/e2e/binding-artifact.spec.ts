import { expect, test } from '@playwright/test';
import { decodeResults } from '../src/api/decoders';
import packageMetadata from '../package.json' with { type: 'json' };

for (const width of [390, 1672]) {
  test(`shared binding evidence stays source-owned through real read UI at ${width}px`, async ({
    page,
  }) => {
    expect(process.env.PATENTSAR_E2E_BINDING_TRANSPORT).toBe('shared-json-1');
    const source = process.env.PATENTSAR_E2E_SOURCE_PROJECT_ID;
    expect(source).toBeTruthy();
    const writes: string[] = [],
      errors: string[] = [];
    page.on('pageerror', (error) => errors.push(error.message));
    await page.route('**/api/v1/**', async (route) => {
      if (route.request().method() !== 'GET') {
        writes.push(route.request().method() + ' ' + new URL(route.request().url()).pathname);
        await route.abort();
      } else await route.continue();
    });
    await page.setViewportSize({ width, height: 1060 });
    await page.goto('/#/projects/' + source);
    await expect(page.locator('.topbar')).toContainText(`v${packageMetadata.version}`);
    const response = await page.request.get(
      `/api/v1/projects/${source}/results?page=1&page_size=100`,
    );
    expect(response.ok()).toBe(true);
    const original = decodeResults(await response.json());
    expect(original.total).toBe(30);
    expect(original.items).toHaveLength(30);
    // All are controlled historical review rows, never model/extraction proof.
    expect(original.items.every((row) => row.confidence.level !== 'high')).toBe(true);
    const first = original.items[0];
    if (!first) throw new Error('The controlled shared-artifact fixture has no result rows');
    const trigger = page.locator(`tr[data-compound="${first.id}"] .frozen-compound button`);
    await expect(trigger).toBeVisible();
    await trigger.click();
    const dialog = page.getByRole('dialog', { name: /^Structure details/ });
    await expect(dialog).toBeVisible();
    await expect
      .poll(() =>
        dialog
          .locator('img')
          .evaluateAll(
            (images) =>
              images.length > 0 &&
              images.every(
                (image) =>
                  (image as HTMLImageElement).complete &&
                  (image as HTMLImageElement).naturalWidth > 0,
              ),
          ),
      )
      .toBe(true);
    await dialog.screenshot({ path: test.info().outputPath(`binding-source-en-${width}.png`) });
    await page
      .getByRole('combobox', { name: 'Interface language', exact: true })
      .selectOption('zh-CN');
    await expect(page.getByRole('dialog', { name: /^结构详情/ })).toBeVisible();
    await page.keyboard.press('Escape');
    await expect(trigger).toBeFocused();
    await page.reload();
    const persisted = await page.request.get(
      `/api/v1/projects/${source}/results?page=1&page_size=100`,
    );
    expect(persisted.ok()).toBe(true);
    expect(decodeResults(await persisted.json()).items).toEqual(original.items);
    await expect(trigger).toBeVisible();
    if (width > 390) {
      const originalPage = page.locator('.page-canvas img');
      await expect(originalPage).toBeVisible();
      await expect
        .poll(() =>
          originalPage.evaluate(
            (image) =>
              (image as HTMLImageElement).complete && (image as HTMLImageElement).naturalWidth > 0,
          ),
        )
        .toBe(true);
      await expect(page.locator('.page-loading')).toHaveCount(0);
    }
    await page.screenshot({ path: test.info().outputPath(`binding-source-zh-${width}.png`) });
    expect(errors).toEqual([]);
    expect(writes).toEqual([]);
  });
}
