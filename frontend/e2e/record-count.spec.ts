import { expect, test } from '@playwright/test';
import { decodeResults } from '../src/api/decoders';
import type { Results } from '../src/api/types';
import packageMetadata from '../package.json' with { type: 'json' };

function range(result: Results) {
  return result.total > 0
    ? ` · ${(result.page - 1) * result.page_size + 1}–${Math.min(result.page * result.page_size, result.total)}`
    : '';
}

for (const width of [390, 1672]) {
  test(`record totals remain neutral and source-owned across paging and languages at ${width}px`, async ({
    page,
  }) => {
    const source = process.env.PATENTSAR_E2E_SOURCE_PROJECT_ID;
    expect(source).toBeTruthy();
    const writes: string[] = [],
      errors: string[] = [];
    let releaseResults!: () => void;
    const resultsReady = new Promise<void>((resolve) => {
      releaseResults = resolve;
    });
    page.on('pageerror', (error) => errors.push(error.message));
    await page.route('**/api/v1/**', async (route) => {
      if (route.request().method() !== 'GET') {
        writes.push(new URL(route.request().url()).pathname);
        await route.abort();
      } else {
        if (new URL(route.request().url()).pathname.endsWith('/results')) await resultsReady;
        await route.continue();
      }
    });
    await page.setViewportSize({ width, height: 1060 });
    try {
      await page.goto('/#/projects/' + source);
      await expect(page.locator('.topbar')).toContainText(`v${packageMetadata.version}`);
      await expect(page.locator('.pagination span.muted')).toHaveText('Record count unknown');
      await expect(page.getByRole('combobox', { name: 'Records per page' })).toBeDisabled();
    } finally {
      // Delay only this GET, then release the actual installed backend response.
      // No fake count/response, write, scientific task or fixed sleep is used.
      releaseResults();
    }
    const response = await page.request.get(
      `/api/v1/projects/${source}/results?page=1&page_size=25`,
    );
    expect(response.ok()).toBe(true);
    const initial = decodeResults(await response.json());
    const footer = page.locator('.pagination');
    await expect(footer.locator('span.muted')).toHaveText(
      `${initial.total} records${range(initial)}`,
    );
    const changedResponse = page
      .waitForResponse((result) => {
        const url = new URL(result.url());
        return (
          result.request().method() === 'GET' &&
          url.pathname === `/api/v1/projects/${source}/results` &&
          url.searchParams.get('page_size') === '100'
        );
      })
      .then((response) => response.ok());
    await footer.getByRole('combobox', { name: 'Records per page' }).selectOption('100');
    expect(await changedResponse).toBe(true);
    // A normal job hydration can retire an earlier CDP body handle. Observe the
    // UI fetch, then read the same query through the authenticated GET context.
    const persisted = await page.request.get(
      `/api/v1/projects/${source}/results?page=1&page_size=100`,
    );
    expect(persisted.ok()).toBe(true);
    const changed = decodeResults(await persisted.json());
    expect(changed.total).toBe(initial.total);
    expect(changed.page).toBe(1);
    expect(changed.page_size).toBe(100);
    await expect(footer.locator('span.muted')).toHaveText(
      `${changed.total} records${range(changed)}`,
    );
    await footer.screenshot({ path: test.info().outputPath(`record-count-en-${width}.png`) });
    await page.getByRole('combobox', { name: 'Interface language' }).selectOption('zh-CN');
    await expect(footer.locator('span.muted')).toHaveText(
      `共 ${changed.total} 条记录${range(changed)}`,
    );
    await expect(footer.getByRole('combobox', { name: '每页记录数量' })).toHaveValue('100');
    expect(await footer.evaluate((node) => node.scrollWidth <= node.clientWidth + 1)).toBe(true);
    await footer.screenshot({ path: test.info().outputPath(`record-count-zh-${width}.png`) });
    expect(errors).toEqual([]);
    expect(writes).toEqual([]);
  });
}
