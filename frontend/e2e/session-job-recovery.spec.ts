import { expect, test } from '@playwright/test';
import { job } from '../tests/fixtures';

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
