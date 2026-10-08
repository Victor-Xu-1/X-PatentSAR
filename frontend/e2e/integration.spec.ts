import { existsSync } from 'node:fs';
import { expect, test } from '@playwright/test';
import packageMetadata from '../package.json' with { type: 'json' };
import type { Health, Job, Project, Results } from '../src/api/types';

const expectedVersion = packageMetadata.version;
const pdfPath =
  process.env.PATENTSAR_E2E_PDF ??
  '/srv/wsl/data/patentsar/inputs/WO2025264818-PAMPH-20251226-0041.pdf';
const historyId = process.env.PATENTSAR_E2E_HISTORY_PROJECT_ID;
const failureId = process.env.PATENTSAR_E2E_FAILED_JOB_ID;

test.describe('real local backend integration', () => {
  test.describe.configure({ mode: 'serial' });
  test.beforeAll(async ({ request }) => {
    await expect
      .poll(
        async () => {
          try {
            const response = await request.get('/api/v1/health', { timeout: 2500 });
            return response.ok() && (await response.json()).ready === true;
          } catch {
            return false;
          }
        },
        { timeout: 45000, intervals: [250, 500, 1000] },
      )
      .toBe(true);
    if (
      process.env.CI &&
      (!existsSync(pdfPath) ||
        !historyId ||
        !failureId ||
        process.env.PATENTSAR_E2E_RUN_JOBS !== '1')
    ) {
      throw new Error(
        'CI requires PDF, history, failed-job and owned-job fixtures; integration cases must not be skipped',
      );
    }
  });
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
      await expect(page.getByRole('heading', { name: '上传专利 PDF' })).toBeVisible();
      await expect(page.getByRole('button', { name: '上传 PDF', exact: true })).toBeEnabled();
      await expect(page.getByRole('button', { name: '开始提取' })).toBeDisabled();
      await expect(page.locator('.sidebar')).toHaveCount(0);
      expect(
        await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth + 2),
      ).toBe(true);
      await expect(page.locator('.topbar-version')).toHaveText(`v${expectedVersion}`);
      await page.getByRole('button', { name: '环境管理', exact: true }).click();
      await expect(page.getByRole('heading', { name: '环境管理' })).toBeVisible();
      await expect(page.getByRole('heading', { name: '完整运行环境', exact: true })).toBeVisible();
      await expect(page.getByRole('button', { name: '存储位置', exact: true })).toBeVisible();
      expect(errors).toEqual([]);
    });
  }
  test('raw real PDF upload, cookie/CSRF, page navigation and refresh', async ({ page }) => {
    test.skip(!existsSync(pdfPath), 'Set PATENTSAR_E2E_PDF to an approved real PDF outside source');
    test.skip(
      process.env.PATENTSAR_E2E_RUN_JOBS !== '1',
      'Uploading now starts the complete task; real job execution requires explicit opt-in',
    );
    await page.goto('/#/');
    await expect(page.getByRole('button', { name: '上传 PDF', exact: true })).toBeEnabled();
    const health = (await (await page.request.get('/api/v1/health')).json()) as Health;
    expect(
      health.capabilities.admet,
      'The complete upload workflow requires a configured real ADMET runtime',
    ).toBe(true);
    await page.getByRole('button', { name: '上传 PDF', exact: true }).click();
    await page.getByLabel('原始专利 PDF 文件').setInputFiles(pdfPath);
    await expect(page.getByRole('radio')).toHaveCount(0);
    await expect(page.locator('.task-advanced')).toHaveCount(0);
    const uploaded = page.waitForResponse(
      (response) =>
        response.request().method() === 'POST' && /\/api\/v1\/projects\?/.test(response.url()),
    );
    const started = page.waitForResponse(
      (response) =>
        response.request().method() === 'POST' &&
        /\/projects\/[^/]+\/jobs$/.test(new URL(response.url()).pathname),
    );
    await page.getByRole('button', { name: '开始提取' }).click();
    const response = await uploaded;
    expect(response.status()).toBe(201);
    const request = response.request();
    expect(request.headers()['content-type']).toBe('application/pdf');
    expect(request.headers()['x-csrf-token']).toBeTruthy();
    const startResponse = await started;
    expect(startResponse.status()).toBe(202);
    expect(startResponse.request().postDataJSON()).toEqual({
      include_admet: true,
      include_intermediates: false,
      force: false,
      task_note: '',
      allow_partial: false,
      advisory: false,
      resume_job_id: null,
    });
    const createdJob = (await startResponse.json()) as Job;
    // Chromium may evict an upload's inspector body when the app navigates.
    // Verify the durable result through its authenticated API after navigation.
    await expect(page).toHaveURL(/#\/projects\/[a-f0-9]{32}/);
    const projectId = page.url().match(/#\/projects\/([a-f0-9]{32})/)?.[1];
    expect(projectId).toBeTruthy();
    const uploadedId = projectId!;
    const jobsResponse = await page.request.get(`/api/v1/jobs?project_id=${uploadedId}`);
    expect(jobsResponse.ok()).toBe(true);
    expect(
      ((await jobsResponse.json()) as { items: Job[] }).items.find(
        (job) => job.id === createdJob.id,
      ),
    ).toMatchObject({
      include_admet: true,
      include_intermediates: false,
      force: false,
      task_note: '',
    });
    const persisted = await page.request.get(`/api/v1/projects/${uploadedId}`);
    expect(persisted.ok()).toBe(true);
    const project = (await persisted.json()) as Project;
    expect(project.id).toBe(uploadedId);
    expect(project.pdf.page_count).toBeGreaterThan(0);
    // Deliberate cover browsing is not the initial automatic structure-page selection.
    const pageInput = page.getByLabel('原始文档页码');
    await pageInput.fill('1');
    await pageInput.press('Enter');
    await expect(page.getByRole('img', { name: '原始专利 PDF 第 1 页' })).toBeVisible();
    const image = page.getByRole('img', { name: '原始专利 PDF 第 1 页' });
    await expect
      .poll(() => image.evaluate((img) => (img as HTMLImageElement).naturalWidth))
      .toBeGreaterThan(0);
    const bounds = await image.boundingBox();
    const frame = await page.locator('.pdf-scroll').boundingBox();
    expect(bounds!.width).toBeLessThanOrEqual(frame!.width);
    expect(bounds!.x).toBeGreaterThanOrEqual(frame!.x);
    expect(bounds!.x + bounds!.width).toBeLessThanOrEqual(frame!.x + frame!.width);
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
    await page.getByRole('button', { name: '文档工具' }).click();
    await page.getByLabel('放大原始文档').click();
    await expect(page.getByLabel('文档缩放比例')).toHaveText('125%');
    await page.keyboard.press('Escape');
    const observed = (await (
      await page.request.get(`/api/v1/jobs/${createdJob.id}`)
    ).json()) as Job;
    if (observed.status === 'queued' || observed.status === 'running') {
      await page.getByRole('button', { name: '取消任务', exact: true }).click();
      await page.getByRole('button', { name: '确认取消此任务' }).click();
      await expect(page.locator('.stage-current')).toContainText('已取消');
    }
    await page.reload();
    const stopped = (await (await page.request.get(`/api/v1/jobs/${createdJob.id}`)).json()) as Job;
    expect(['complete', 'failed', 'cancelled', 'interrupted']).toContain(stopped.status);
    await page.getByRole('button', { name: '任务详情' }).click();
    await expect(page.locator('.job-options-record')).toBeVisible();
  });
  test('real historical results, pagination, actual source availability, review persistence and export', async ({
    page,
  }) => {
    test.skip(
      !historyId,
      'Set PATENTSAR_E2E_HISTORY_PROJECT_ID to an approved isolated import with real artifacts; the review note is persisted',
    );
    const loaded = page.waitForResponse((value) => value.url().includes('/results?') && value.ok());
    await page.goto(`/#/projects/${encodeURIComponent(historyId!)}?page=1&tab=original`);
    const response = await loaded;
    const persistedResults = await page.request.get(response.url());
    expect(persistedResults.ok()).toBe(true);
    const result = (await persistedResults.json()) as Results;
    expect(result.items.length).toBeGreaterThan(0);
    const projectResponse = await page.request.get(`/api/v1/projects/${historyId}`);
    const project = (await projectResponse.json()) as Project;
    if (project.pdf.available) {
      await expect(page.getByRole('img', { name: '原始专利 PDF 第 1 页' })).toBeVisible();
      await expect(page.getByText('尚未提供原始 PDF')).toHaveCount(0);
    } else await expect(page.getByText(/尚未提供原始 PDF|原始 PDF 页面不可用/)).toBeVisible();
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
        .getByRole('button', { name: /结构来源第 \d+ 页$/ })
        .click();
      await expect(page.getByRole('tab', { name: '结构标注' })).toHaveAttribute(
        'aria-selected',
        'true',
      );
      await expect(page).toHaveURL(/compound=/);
    }
    if (compound.structure_image_url) {
      await page.getByLabel(`放大 ${compound.display_id} 结构裁图`).click();
      await expect(
        page
          .getByRole('dialog')
          .getByRole('img', { name: `${compound.display_id} 的原始结构裁图`, exact: true }),
      ).toBeVisible();
      await page.getByLabel('关闭对话框').click();
    }
    await page.getByLabel(`选择化合物 ${compound.display_id}`, { exact: true }).check();
    await page.getByLabel(`修正 ${compound.display_id}`, { exact: true }).click();
    await expect(page.getByLabel('结构式绘制区域')).toBeVisible();
    await expect(page.getByLabel('修正 MW')).toBeVisible();
    await page.getByRole('button', { name: '取消', exact: true }).click();
    await page.getByRole('button', { name: /导出所选/ }).click();
    const downloaded = page.waitForEvent('download');
    await page.getByRole('button', { name: '生成并下载' }).click();
    const download = await downloaded;
    expect(download.suggestedFilename()).toMatch(/\.csv$/);
    expect(await download.failure()).toBeNull();
    await page.getByRole('button', { name: '关闭', exact: true }).click();
    const filtered = page.waitForResponse(
      (value) =>
        value.url().includes('/results?') &&
        value.ok() &&
        new URL(value.url()).searchParams.get('q') === compound.display_id,
    );
    await page.getByLabel('搜索结果', { exact: true }).fill(compound.display_id);
    const filteredResponse = await filtered;
    const durableFiltered = await page.request.get(filteredResponse.url());
    const filteredResults = (await durableFiltered.json()) as Results;
    expect(filteredResults.total).toBeGreaterThan(0);
    await expect(page.locator('.pagination')).toContainText(`共 ${filteredResults.total} 个化合物`);
    await page.getByRole('button', { name: '导出结果', exact: true }).click();
    await page.getByLabel('导出范围').selectOption('filtered');
    await page.getByLabel('文件格式').selectOption('json');
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
    const actualDownload = await filteredDownload;
    expect(await actualDownload.failure()).toBeNull();
    const stream = await actualDownload.createReadStream();
    expect(stream).not.toBeNull();
    const chunks: Buffer[] = [];
    for await (const chunk of stream!) chunks.push(Buffer.from(chunk));
    const downloadedJson = JSON.parse(Buffer.concat(chunks).toString('utf8')) as {
      items: unknown[];
      review_only: boolean;
    };
    expect(downloadedJson.items).toHaveLength(filteredResults.total);
    expect(downloadedJson.review_only).toBe(true);
  });
  test('an actual failed job remains a failure and exposes its real stage/error', async ({
    page,
  }) => {
    test.skip(
      !failureId,
      'Set PATENTSAR_E2E_FAILED_JOB_ID to a real failed job from the controller acceptance run',
    );
    await page.goto('/#/');
    await expect(page.getByRole('button', { name: '上传 PDF', exact: true })).toBeEnabled();
    const response = await page.request.get(`/api/v1/jobs/${encodeURIComponent(failureId!)}`);
    expect(response.ok()).toBe(true);
    const job = (await response.json()) as Job;
    expect(job.status).toBe('failed');
    expect(job.error).not.toBeNull();
    await page.goto('/#/jobs');
    const card = page.locator('.job-card').filter({ hasText: job.id });
    await expect(card).toBeVisible();
    await expect(card.locator('.job-actions .badge')).toHaveText('运行失败');
    await expect(card.locator('.job-error')).toContainText(job.error!.message);
  });
});
