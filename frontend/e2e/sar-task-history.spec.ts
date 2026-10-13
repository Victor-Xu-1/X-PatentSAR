import { expect, test } from '@playwright/test';
import { createNetwork } from './sar-network-actions';

for (const width of [390, 800, 1672])
  test(`two task modules and retained native SAR history at ${width}`, async ({ page }, info) => {
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
    const first = await createNetwork(page, width);
    const second = await createNetwork(page, width + 1);
    const before = await (
      await page.request.get(`/api/v1/sar/jobs/${first.job}/study/export?format=json`)
    ).text();
    const pageWrites: string[] = [];
    page.on('request', (request) => {
      if (request.method() !== 'GET') pageWrites.push(request.url());
    });
    await page.goto('/#/jobs');
    await expect(page.getByRole('tab', { name: 'Patent extraction', exact: true })).toHaveAttribute(
      'aria-selected',
      'true',
    );
    await page.getByRole('tab', { name: 'SAR analysis', exact: true }).click();
    await expect(page).toHaveURL(/#\/jobs\?module=sar$/);
    const sar = page.getByRole('region', { name: 'SAR analysis tasks', exact: true });
    const firstRow = sar.locator(`[data-job-id="${first.job}"]`),
      secondRow = sar.locator(`[data-job-id="${second.job}"]`);
    await expect(firstRow).toBeVisible();
    await expect(secondRow).toBeVisible();
    await expect(firstRow.getByRole('button', { name: 'View results', exact: true })).toBeEnabled();
    await sar.getByLabel('Filter SAR datasets', { exact: true }).selectOption(first.dataset);
    await expect(secondRow).toHaveCount(0);
    await expect(firstRow).toBeVisible();
    await page.screenshot({ path: info.outputPath(`history-sar-en-${width}.png`), fullPage: true });
    await firstRow.getByRole('button', { name: 'View results', exact: true }).click();
    await expect(page).toHaveURL(new RegExp(`dataset=${first.dataset}&job=${first.job}`));
    await expect(page.getByRole('region', { name: 'Study report', exact: true })).toBeVisible();
    expect(
      await (
        await page.request.get(`/api/v1/sar/jobs/${first.job}/study/export?format=json`)
      ).text(),
    ).toBe(before);
    await page.goto('/#/jobs?module=sar');
    await page.reload();
    await expect(page.getByRole('tab', { name: 'SAR analysis', exact: true })).toHaveAttribute(
      'aria-selected',
      'true',
    );
    await page.locator('.language-switch select').selectOption('zh-CN');
    const localized = page.getByRole('region', { name: 'SAR 分析任务', exact: true });
    await expect(localized.locator(`[data-job-id="${first.job}"]`)).toBeVisible();
    await page.screenshot({ path: info.outputPath(`history-sar-zh-${width}.png`), fullPage: true });
    await page.getByRole('tab', { name: '专利提取', exact: true }).click();
    await expect(page).toHaveURL(/#\/jobs$/);
    await expect(page.getByLabel('筛选任务所属项目')).toBeVisible();
    await page.getByRole('button', { name: '回收站', exact: true }).click();
    await expect(page.getByRole('dialog', { name: '回收站', exact: true })).toBeVisible();
    await page.keyboard.press('Escape');
    await expect(page.getByRole('dialog')).toHaveCount(0);
    await page.screenshot({
      path: info.outputPath(`history-patent-zh-${width}.png`),
      fullPage: true,
    });
    expect(pageWrites).toEqual([]);
    await page.getByRole('tab', { name: 'SAR 分析', exact: true }).click();
    const target = page.locator(`[data-job-id="${second.job}"]`);
    await target.getByRole('button', { name: '移除 SAR 任务', exact: true }).click();
    await page.getByRole('dialog').getByRole('button', { name: '确认软移除', exact: true }).click();
    await expect(target).toHaveCount(0);
    expect((await page.request.get(`/api/v1/sar/datasets/${second.dataset}`)).ok()).toBe(true);
    expect(
      await (
        await page.request.get(`/api/v1/sar/jobs/${first.job}/study/export?format=json`)
      ).text(),
    ).toBe(before);
    expect(pageWrites).toEqual([expect.stringContaining(`/api/v1/sar/jobs/${second.job}`)]);
    expect(errors).toEqual([]);
    expect(foreignWrites).toEqual([]);
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth + 1)).toBe(
      true,
    );
  });
