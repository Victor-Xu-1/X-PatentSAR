import { expect, test } from '@playwright/test';
import { job, results } from '../tests/fixtures';

for (const width of [390, 1672]) {
  test(`pending result copy survives a background detail read at ${width}`, async ({
    page,
  }, info) => {
    const origin = new URL(process.env.PATENTSAR_E2E_BASE_URL!);
    expect(['127.0.0.1', 'localhost', '[::1]']).toContain(origin.hostname);
    expect(Number(origin.port)).toBeGreaterThanOrEqual(18766);
    expect(Number(origin.port)).toBeLessThanOrEqual(18866);
    expect(process.env.PATENTSAR_E2E_RUN_JOBS).toBe('0');
    const projectId = process.env.PATENTSAR_E2E_SOURCE_PROJECT_ID!;
    const current = { ...job, id: 'controlled-pending-read-job', project_id: projectId };
    let holdNextDetail = false,
      detailPending = false;
    let releaseDetail: (() => void) | undefined;
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
      const list = url.pathname === '/api/v1/jobs';
      const detail = url.pathname === `/api/v1/jobs/${current.id}`;
      if (detail && holdNextDetail) {
        holdNextDetail = false;
        detailPending = true;
        await new Promise<void>((resolve) => {
          releaseDetail = resolve;
        });
        detailPending = false;
      }
      if (list || detail) return route.fulfill({ json: list ? { items: [current] } : current });
      if (url.pathname === `/api/v1/projects/${projectId}/results`)
        return route.fulfill({ json: { ...results, project_id: projectId, items: [], total: 0 } });
      return route.continue();
    });
    try {
      await page.setViewportSize({ width, height: 940 });
      await page.goto(`/#/projects/${projectId}`);
      const cancel = page.getByRole('button', { name: 'Cancel task', exact: true });
      const waiting = page.getByText('Results will appear automatically when ready', {
        exact: true,
      });
      await expect(cancel).toBeEnabled();
      await expect(waiting).toBeVisible();
      holdNextDetail = true;
      await expect.poll(() => detailPending, { timeout: 10000 }).toBe(true);
      await expect(cancel).toBeDisabled();
      await expect(waiting).toBeVisible();
      await expect(
        page.getByText('No confirmed numbered products yet', { exact: true }),
      ).toHaveCount(0);
      await expect(page.getByRole('button', { name: 'Run extraction', exact: true })).toHaveCount(
        0,
      );
      await page.screenshot({
        path: info.outputPath('pending-read-en.png'),
        animations: 'disabled',
      });
      await page
        .getByRole('combobox', { name: 'Interface language', exact: true })
        .selectOption('zh-CN');
      const chineseWaiting = page.getByText('结果就绪后将自动显示', { exact: true });
      const chineseCancel = page.getByRole('button', { name: '取消任务', exact: true });
      await expect(chineseWaiting).toBeVisible();
      await expect(chineseCancel).toBeDisabled();
      await expect(page.getByText('暂无已确认的编号终产物', { exact: true })).toHaveCount(0);
      await page.screenshot({
        path: info.outputPath('pending-read-zh.png'),
        animations: 'disabled',
      });
      releaseDetail?.();
      await expect(chineseCancel).toBeEnabled();
      await expect(chineseWaiting).toBeVisible();
      expect(
        await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth + 1),
      ).toBe(true);
      expect(writes).toEqual([]);
      expect(errors).toEqual([]);
    } finally {
      releaseDetail?.();
    }
  });
}

// Same-origin GET faults over a real installed service and synthetic source.
// No cookie inspection, user source, mutation, model or actual task execution.
for (const width of [390, 800, 1672]) {
  test(`lost-session reads recover without replaying writes and retain unknown task state at ${width}`, async ({
    page,
  }, info) => {
    const origin = new URL(process.env.PATENTSAR_E2E_BASE_URL!);
    expect(['127.0.0.1', 'localhost', '[::1]']).toContain(origin.hostname);
    expect(Number(origin.port)).toBeGreaterThanOrEqual(18766);
    expect(Number(origin.port)).toBeLessThanOrEqual(18866);
    expect(process.env.PATENTSAR_E2E_RUN_JOBS).toBe('0');
    const projectId = process.env.PATENTSAR_E2E_SOURCE_PROJECT_ID!;
    const current = { ...job, id: 'controlled-read-session-job', project_id: projectId };
    let mode: 'healthy' | 'once' | 'denied' = 'healthy';
    let handshakes = 0;
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
      if (url.pathname === '/api/v1/session') handshakes++;
      const list = url.pathname === '/api/v1/jobs';
      const detail = url.pathname === `/api/v1/jobs/${current.id}`;
      if (list || detail) {
        if (mode !== 'healthy') {
          if (mode === 'once') mode = 'healthy';
          return route.fulfill({
            status: 401,
            contentType: 'application/json',
            body: JSON.stringify({
              error: {
                code: 'session_required',
                message: 'Controlled same-origin session unavailable',
              },
            }),
          });
        }
        return route.fulfill({
          status: 200,
          contentType: 'application/json',
          body: JSON.stringify(list ? { items: [current] } : current),
        });
      }
      await route.continue();
    });
    await page.setViewportSize({ width, height: 940 });
    await page.goto(`/#/projects/${projectId}`);
    const cancel = page.getByRole('button', { name: 'Cancel task', exact: true });
    await expect(cancel).toBeEnabled();
    const initial = handshakes;
    mode = 'once';
    await expect.poll(() => handshakes, { timeout: 10000 }).toBe(initial + 1);
    await expect(cancel).toBeEnabled();
    await expect(page.getByRole('alert')).toHaveCount(0);
    await page.screenshot({
      path: info.outputPath('01-safe-read-recovered.png'),
      animations: 'disabled',
    });
    mode = 'denied';
    await expect(page.getByRole('alert')).toContainText(
      'Controlled same-origin session unavailable',
    );
    await expect(cancel).toBeDisabled();
    await expect(page.locator('.stage-current')).toHaveText('Stage status unknown');
    await expect(page.getByRole('button', { name: 'Run extraction', exact: true })).toHaveCount(0);
    const language = page.getByRole('combobox', { name: 'Interface language', exact: true });
    await language.selectOption('zh-CN');
    await expect(page.locator('.stage-current')).toHaveText('阶段状态未知');
    await page.screenshot({
      path: info.outputPath('02-retained-unverified-state.png'),
      animations: 'disabled',
    });
    mode = 'healthy';
    await page.getByRole('alert').getByRole('button', { name: '重新加载', exact: true }).click();
    await expect(page.getByRole('button', { name: '取消任务', exact: true })).toBeEnabled();
    await expect(page.getByRole('alert')).toHaveCount(0);
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth + 1)).toBe(
      true,
    );
    expect(errors).toEqual([]);
    expect(writes).toEqual([]);
  });
}
