import { expect, test } from '@playwright/test';
import type { PageSourcePhase } from '../src/api/types';
import { job } from '../tests/fixtures';

// Synthetic GET telemetry only, against an isolated installed application.
// Never target production, run a PDF/model, upload data or change a real task.
for (const width of [390, 1672]) {
  test(`page-source work remains truthful and bilingual at ${width}px`, async ({ page }, info) => {
    const origin = new URL(process.env.PATENTSAR_E2E_BASE_URL!);
    expect(['127.0.0.1', 'localhost', '[::1]']).toContain(origin.hostname);
    expect(Number(origin.port)).toBeGreaterThanOrEqual(18766);
    expect(Number(origin.port)).toBeLessThanOrEqual(18866);
    expect(process.env.PATENTSAR_E2E_RUN_JOBS).toBe('0');
    const project = process.env.PATENTSAR_E2E_SOURCE_PROJECT_ID!;
    let phase: PageSourcePhase = 'page_ocr';
    let completed = 7,
      total = 13,
      cacheHits = 2;
    let terminal = false,
      unavailable = false,
      unavailableReads = 0,
      resultReads = 0;
    const writes: string[] = [],
      errors: string[] = [];
    page.on('pageerror', (error) => errors.push(error.message));
    await page.route('**/api/v1/**', async (route) => {
      const request = route.request(),
        url = new URL(request.url());
      if (request.method() !== 'GET') {
        writes.push(url.pathname);
        return route.abort();
      }
      if (url.pathname === `/api/v1/projects/${project}/results`) resultReads++;
      const list = url.pathname === '/api/v1/jobs';
      if (!list && url.pathname !== '/api/v1/jobs/controlled-page-work') return route.continue();
      if (unavailable) {
        unavailableReads++;
        return route.fulfill({
          status: 503,
          contentType: 'application/json',
          body: JSON.stringify({
            error: { code: 'service_unavailable', message: 'Controlled unavailable observation.' },
          }),
        });
      }
      const current = {
        ...job,
        id: 'controlled-page-work',
        project_id: project,
        status: terminal ? 'failed' : 'running',
        error: terminal
          ? { code: 'extraction_failed', message: 'Controlled source failure.' }
          : null,
        stages: job.stages.map((stage) => ({
          ...stage,
          count: null,
          status: stage.name === 'classify' ? (terminal ? 'failed' : 'running') : 'pending',
          progress:
            stage.name === 'classify'
              ? {
                  phase: null,
                  source_phase: phase,
                  completed,
                  total,
                  cache_hits: cacheHits,
                  failures: 0,
                  device: null,
                  peak_rss_mb: null,
                }
              : null,
        })),
      };
      return route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify(list ? { items: [current] } : current),
      });
    });
    await page.setViewportSize({ width, height: 1060 });
    await page.goto(`/#/projects/${project}`);
    const current = page.locator('.stage-current');
    await expect(current).toContainText('Reading original pages · 7 / 13 pages');
    await expect(current).toHaveClass(/is-running/);
    await expect.poll(() => resultReads).toBeGreaterThan(0);
    const count = resultReads;
    await page.locator('.stage-current-line').click();
    const disclosure = page.locator('.stage-disclosure');
    const observation = page
      .locator('.stage-observation')
      .filter({ hasText: 'Reading original pages' });
    await observation.locator('summary').click();
    await expect(observation).toContainText('Reused 2 original page observations');
    await expect(observation).toContainText('does not certify complete extraction');
    const bounds = await disclosure.locator('.stage-detail-surface').boundingBox();
    expect(bounds!.x).toBeGreaterThanOrEqual(8);
    expect(bounds!.x + bounds!.width).toBeLessThanOrEqual(width - 8);
    await page.screenshot({ path: info.outputPath('01-pages-en.png'), animations: 'disabled' });
    await page.keyboard.press('Escape');
    phase = 'empty_text_retry';
    completed = 0;
    total = 2;
    cacheHits = 0;
    await expect(current).toContainText('Re-reading empty text observations · 0 / 2 pages');
    await page.locator('.stage-current-line').click();
    const retry = page
      .locator('.stage-observation')
      .filter({ hasText: 'Re-reading empty text observations' });
    await retry.locator('summary').click();
    await expect(retry).toContainText('does not establish a blank source page');
    await page.keyboard.press('Escape');
    phase = 'page_classification';
    completed = total = 13;
    await expect(current).toContainText('Classifying pages · 13 / 13 pages');
    await expect(current).toHaveClass(/is-running/);
    await expect(current).not.toContainText('Run complete');
    expect(resultReads).toBe(count);
    unavailable = true;
    await expect.poll(() => unavailableReads).toBeGreaterThan(0);
    await expect(current).toHaveText('Stage status unknown');
    await expect(page.getByRole('button', { name: 'Cancel task', exact: true })).toBeDisabled();
    await expect(page.getByRole('button', { name: 'Run extraction', exact: true })).toHaveCount(0);
    unavailable = false;
    await expect(current).toContainText('Classifying pages · 13 / 13 pages');
    await expect(page.getByRole('button', { name: 'Cancel task', exact: true })).toBeEnabled();
    terminal = true;
    completed = total = 10001;
    await expect(current).toHaveClass(/is-failed/);
    await expect(current.locator('.stage-current-text')).toHaveText(
      'Run failed · Document parsing',
    );
    await expect(current).toHaveAttribute('title', /Classifying pages · 10001 \/ 10001 pages/);
    expect((await current.boundingBox())!.height).toBeLessThanOrEqual(36);
    await page
      .getByRole('combobox', { name: 'Interface language', exact: true })
      .selectOption('zh-CN');
    await expect(current.locator('.stage-current-text')).toHaveText('运行失败 · 文档解析');
    await expect(current).toHaveAttribute('title', /分析页面用途 · 10001 \/ 10001 页/);
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth + 1)).toBe(
      true,
    );
    await page.screenshot({
      path: info.outputPath('02-pages-failed-zh.png'),
      animations: 'disabled',
    });
    expect(errors).toEqual([]);
    expect(writes).toEqual([]);
  });
}
