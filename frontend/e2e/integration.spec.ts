import { existsSync } from 'node:fs';
import { expect, test } from '@playwright/test';
import type { Job, Results } from '../src/api/types';

const pdfPath =
  process.env.PATENTSAR_E2E_PDF ??
  '/srv/wsl/data/patentsar/inputs/WO2025264818-PAMPH-20251226-0041.pdf';
const historyId = process.env.PATENTSAR_E2E_HISTORY_PROJECT_ID;
const failureId = process.env.PATENTSAR_E2E_FAILED_JOB_ID;
let uploadedId = '';

test.describe('real local backend integration', () => {
  test.describe.configure({ mode: 'serial' });
  for (const viewport of [
    { width: 1672, height: 942 },
    { width: 1280, height: 800 },
    { width: 390, height: 844 },
  ]) {
    test(`clean workspace, session and navigation at ${viewport.width}×${viewport.height}`, async ({
      page,
    }) => {
      const errors: string[] = [];
      page.on('pageerror', (error) => errors.push(error.message));
      await page.setViewportSize(viewport);
      await page.goto('/#/');
      await expect(page.getByText('开始探索专利中的结构与活性')).toBeVisible();
      await expect(page.getByText(/^v\d/)).toBeVisible();
      await expect(page.getByRole('button', { name: '运行提取' })).toBeDisabled();
      expect(
        await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth + 2),
      ).toBe(true);
      if (viewport.width < 760) await page.getByLabel('展开或收起导航').click();
      await page.getByRole('button', { name: '运行环境', exact: true }).click();
      await expect(page.getByRole('heading', { name: '运行环境' })).toBeVisible();
      await expect(page.getByText('产品与存储')).toBeVisible();
      expect(errors).toEqual([]);
    });
  }
  test('raw real PDF upload, cookie/CSRF, page navigation and refresh', async ({ page }) => {
    test.skip(!existsSync(pdfPath), 'Set PATENTSAR_E2E_PDF to an approved real PDF outside source');
    await page.goto('/#/');
    await expect(page.getByText(/^v\d/)).toBeVisible();
    await page.getByRole('button', { name: '上传 PDF', exact: true }).click();
    await page.getByLabel('项目名称').fill(`浏览器验收 ${new Date().toISOString()}`);
    await page.getByLabel('原始专利 PDF 文件').setInputFiles(pdfPath);
    const uploaded = page.waitForResponse(
      (response) =>
        response.request().method() === 'POST' && /\/api\/v1\/projects\?/.test(response.url()),
    );
    await page.getByRole('button', { name: '上传并创建项目' }).click();
    const response = await uploaded;
    expect(response.status()).toBe(201);
    const request = response.request();
    expect(request.headers()['content-type']).toBe('application/pdf');
    expect(request.headers()['x-csrf-token']).toBeTruthy();
    const project = (await response.json()) as { id: string; pdf: { page_count: number } };
    uploadedId = project.id;
    await expect(page).toHaveURL(new RegExp(encodeURIComponent(uploadedId)));
    await expect(page.getByRole('img', { name: '原始专利 PDF 第 1 页' })).toBeVisible();
    const pageInput = page.getByLabel('原始文档页码');
    await pageInput.fill(String(Math.min(2, project.pdf.page_count)));
    await pageInput.press('Enter');
    await page.getByRole('tab', { name: '文本视图' }).click();
    await page.reload();
    await expect(page.getByRole('tab', { name: '文本视图' })).toHaveAttribute(
      'aria-selected',
      'true',
    );
    await expect(pageInput).toHaveValue(String(Math.min(2, project.pdf.page_count)));
    await page.getByRole('tab', { name: '原文视图' }).click();
    await page.getByLabel('放大原始文档').click();
    await expect(page.getByLabel('文档缩放比例')).toHaveText('125%');
  });
  test('real historical results, pagination, source absence, review persistence and export', async ({
    page,
  }) => {
    test.skip(
      !historyId,
      'Set PATENTSAR_E2E_HISTORY_PROJECT_ID to an approved isolated import with real artifacts; the review note is persisted',
    );
    const loaded = page.waitForResponse((value) => value.url().includes('/results?') && value.ok());
    await page.goto(`/#/projects/${encodeURIComponent(historyId!)}?page=1&tab=original`);
    const response = await loaded;
    const result = (await response.json()) as Results;
    expect(result.items.length).toBeGreaterThan(0);
    await expect(page.getByText(/尚未提供原始 PDF|原始 PDF 页面不可用/)).toBeVisible();
    if (result.total > result.page_size) {
      await page.getByLabel('下一页结果').click();
      await expect(page.getByRole('button', { name: '结果第 2 页' })).toHaveAttribute(
        'aria-current',
        'page',
      );
      await page.getByLabel('上一页结果').click();
    }
    const compound = result.items[0]!;
    if (compound.source.page !== null) {
      await page
        .locator('.results-table tbody tr')
        .first()
        .getByRole('button', { name: '来源定位' })
        .click();
      await expect(page.getByRole('tab', { name: '结构标注' })).toHaveAttribute(
        'aria-selected',
        'true',
      );
      await expect(page).toHaveURL(/compound=/);
    }
    if (compound.structure_image_url) {
      await page.getByLabel(`放大 ${compound.display_id} 结构裁图`).click();
      await expect(page.getByRole('dialog').getByRole('img')).toBeVisible();
      await page.getByLabel('关闭对话框').click();
    }
    await page.getByLabel(`选择化合物 ${compound.display_id}`).check();
    await page.getByLabel(`复核 ${compound.display_id}`, { exact: true }).click();
    const note = `真实浏览器复核 ${new Date().toISOString()}`;
    await page.getByLabel('复核注记').fill(note);
    await page.getByRole('button', { name: '保存复核注记' }).click();
    await expect(page.getByRole('dialog')).toHaveCount(0);
    await page.reload();
    await page.getByLabel(`复核 ${compound.display_id}`, { exact: true }).click();
    await expect(page.getByLabel('复核注记')).toHaveValue(note);
    await page.getByRole('button', { name: '取消', exact: true }).click();
    await page.getByLabel(`选择化合物 ${compound.display_id}`).check();
    await page.getByRole('button', { name: /导出所选/ }).click();
    const downloaded = page.waitForEvent('download');
    await page.getByRole('button', { name: '生成并下载' }).click();
    const download = await downloaded;
    expect(download.suggestedFilename()).toMatch(/\.csv$/);
    expect(await download.failure()).toBeNull();
    await page.getByRole('button', { name: '关闭', exact: true }).click();
    const filtered = page.waitForResponse(
      (value) => value.url().includes('/results?') && value.ok(),
    );
    await page.getByLabel('搜索结果', { exact: true }).fill(compound.display_id);
    expect(((await (await filtered).json()) as Results).total).toBeGreaterThan(0);
    await page.getByRole('button', { name: '导出结果', exact: true }).click();
    await page.getByLabel('导出范围').selectOption('filtered');
    const exported = page.waitForResponse(
      (value) => value.request().method() === 'POST' && value.url().includes('/export?'),
    );
    const filteredDownload = page.waitForEvent('download');
    await page.getByRole('button', { name: '生成并下载' }).click();
    const exportResponse = await exported;
    const exportUrl = new URL(exportResponse.url());
    expect(exportUrl.searchParams.get('q')).toBe(compound.display_id);
    expect(exportUrl.searchParams.has('page')).toBe(false);
    expect(exportResponse.request().postDataJSON()).toMatchObject({ compound_ids: [] });
    expect(await (await filteredDownload).failure()).toBeNull();
  });
  test('owned real job can be started, cancelled and refreshed', async ({ page }) => {
    test.skip(
      process.env.PATENTSAR_E2E_RUN_JOBS !== '1',
      'Explicit opt-in required for a real extraction process',
    );
    expect(uploadedId, 'Real upload test must have created this owned project').toBeTruthy();
    await page.goto(`/#/projects/${uploadedId}`);
    const run = page.getByRole('button', { name: '运行提取' });
    await expect(run).toBeEnabled();
    await run.click();
    await page.getByRole('button', { name: '取消任务', exact: true }).click();
    await page.getByRole('button', { name: '确认取消此任务' }).click();
    await expect(page.locator('.job-actions .badge')).toHaveText('已取消');
    await page.reload();
    await expect(page.locator('.job-actions .badge')).toHaveText('已取消');
  });
  test('an actual failed job remains a failure and exposes its real stage/error', async ({
    page,
  }) => {
    test.skip(
      !failureId,
      'Set PATENTSAR_E2E_FAILED_JOB_ID to a real failed job from the controller acceptance run',
    );
    await page.goto('/#/');
    await expect(page.getByText(/^v\d/)).toBeVisible();
    const response = await page.request.get(`/api/v1/jobs/${encodeURIComponent(failureId!)}`);
    expect(response.ok()).toBe(true);
    const job = (await response.json()) as Job;
    expect(job.status).toBe('failed');
    expect(job.error).not.toBeNull();
    await page.goto('/#/jobs');
    const card = page.locator('.job-card').filter({ hasText: job.id });
    await expect(card).toBeVisible();
    await expect(card.getByText('运行失败', { exact: true })).toBeVisible();
    await expect(card.locator('.job-error')).toContainText(job.error!.message);
  });
});
