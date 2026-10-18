import { expect, test } from '@playwright/test';
import type { BindingSourcePhase } from '../src/api/types';
import { job } from '../tests/fixtures';

// Installed application over an owned isolated service. Only synthetic GET
// telemetry is varied; no extraction, patent, correction, model or task write.
for (const width of [390, 800, 1672]) {
  test(`binding source passes stay truthful and compact at ${width}px`, async ({ page }, info) => {
    const origin = new URL(process.env.PATENTSAR_E2E_BASE_URL!);
    expect(['127.0.0.1', 'localhost', '[::1]']).toContain(origin.hostname);
    expect(Number(origin.port)).toBeGreaterThanOrEqual(18766);
    expect(Number(origin.port)).toBeLessThanOrEqual(18866);
    expect(process.env.PATENTSAR_E2E_RUN_JOBS).toBe('0');
    const project = process.env.PATENTSAR_E2E_SOURCE_PROJECT_ID!;
    let phase: BindingSourcePhase = 'caption_sources';
    let completed = 2;
    let total = 7;
    let terminal = false;
    let resultReads = 0;
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
      const detail = url.pathname === '/api/v1/jobs/controlled-binding-work';
      if (list || detail) {
        const current = {
          ...job,
          id: 'controlled-binding-work',
          project_id: project,
          status: terminal ? 'failed' : 'running',
          error: terminal
            ? { code: 'extraction_failed', message: 'Controlled source transport failure.' }
            : null,
          // Observe the current recorded source-first chain. Legacy order
          // remains covered independently by the existing task unit checks.
          stage_order: [
            'classify',
            'locate',
            'structures',
            'bind',
            'activity',
            'smiles',
            'final',
            'qa',
          ],
          stages: job.stages.map((stage) => ({
            ...stage,
            status:
              stage.name === 'bind'
                ? terminal
                  ? 'failed'
                  : 'running'
                : ['classify', 'locate', 'structures'].includes(stage.name)
                  ? 'ok'
                  : 'pending',
            progress:
              stage.name === 'bind'
                ? {
                    phase: null,
                    source_phase: phase,
                    completed,
                    total,
                    cache_hits: 0,
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
      }
      await route.continue();
    });
    await page.setViewportSize({ width, height: 1060 });
    await page.goto(`/#/projects/${project}`);
    const current = page.locator('.stage-current');
    await expect(current).toContainText('Checking captions · 2 / 7 pages');
    await expect(current).toHaveClass(/is-running/);
    await expect(page.getByRole('button', { name: 'Cancel task', exact: true })).toBeEnabled();
    await expect.poll(() => resultReads).toBeGreaterThan(0);
    const count = resultReads;
    completed = 5;
    await expect(current).toContainText('Checking captions · 5 / 7 pages');
    phase = 'heading_bindings';
    completed = 7;
    await expect(current).toContainText('Checking identifier ownership · 7 / 7 items');
    await expect(current).toHaveClass(/is-running/);
    await expect(current).not.toContainText('Run complete');
    if (width >= 1280) {
      const groups = page.locator('.workflow-group > span');
      await expect(groups).toHaveCount(4);
      expect(
        await groups.evaluateAll((nodes) =>
          nodes.every((node) => node.scrollWidth <= node.clientWidth + 1),
        ),
      ).toBe(true);
    }
    expect(resultReads).toBe(count);
    await page.locator('.stage-current-line').click();
    const disclosure = page.locator('.stage-disclosure');
    await expect(disclosure).toHaveAttribute('open', '');
    const detailBounds = await disclosure.locator('.stage-detail-surface').boundingBox();
    expect(detailBounds!.x).toBeGreaterThanOrEqual(8);
    expect(detailBounds!.x + detailBounds!.width).toBeLessThanOrEqual(width - 8);
    await page.keyboard.press('Escape');
    await expect(disclosure).not.toHaveAttribute('open');
    await page.locator('.stage-current-line').focus();
    await page.keyboard.press('Enter');
    await expect(disclosure).toHaveAttribute('open', '');
    const source = page
      .locator('.stage-observation')
      .filter({ hasText: 'Checking identifier ownership' });
    await source.locator('summary').click();
    await expect(source).toContainText(
      'Source-check progress does not certify identifiers or chemical structures.',
    );
    await expect(source).not.toContainText('Execution device unknown');
    await page.screenshot({
      path: info.outputPath('01-source-work-en.png'),
      animations: 'disabled',
    });
    await page.keyboard.press('Escape');
    terminal = true;
    completed = total = 73567;
    await expect(current).toHaveClass(/is-failed/);
    await expect(current.locator('.stage-current-text')).toHaveText(
      'Run failed · Identifier binding',
    );
    await expect(current).toHaveAttribute(
      'title',
      /Checking identifier ownership · 73567 \/ 73567 items/,
    );
    await expect(current.locator('.stage-state-icon')).toBeVisible();
    const bounds = await current.boundingBox();
    expect(bounds!.height).toBeLessThanOrEqual(36);
    if (width >= 1280) {
      await expect(page.locator('.workflow-groups')).toBeVisible();
      expect(
        await page
          .locator('.workflow-group > span')
          .evaluateAll((nodes) => nodes.every((node) => node.scrollWidth <= node.clientWidth + 1)),
      ).toBe(true);
    }
    await page.screenshot({
      path: info.outputPath('02-source-failed-en.png'),
      animations: 'disabled',
    });
    await page.locator('.stage-current-line').click();
    await expect(disclosure).toHaveAttribute('open', '');
    await expect(source).toContainText('Checking identifier ownership · 73567 / 73567 items');
    await page.screenshot({
      path: info.outputPath('04-source-failed-details-en.png'),
      animations: 'disabled',
    });
    await page.keyboard.press('Escape');
    await page
      .getByRole('combobox', { name: 'Interface language', exact: true })
      .selectOption('zh-CN');
    await expect(current.locator('.stage-current-text')).toHaveText('运行失败 · 编号绑定');
    await expect(current).toHaveAttribute('title', /核对编号归属 · 73567 \/ 73567 项/);
    await expect(current).toHaveClass(/is-failed/);
    expect((await current.boundingBox())!.height).toBeLessThanOrEqual(36);
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth + 1)).toBe(
      true,
    );
    await page.screenshot({
      path: info.outputPath('03-source-failed-zh.png'),
      animations: 'disabled',
    });
    expect(errors).toEqual([]);
    expect(writes).toEqual([]);
  });
}
