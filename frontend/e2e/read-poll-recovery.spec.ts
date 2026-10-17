import { expect, test } from '@playwright/test';
import { job } from '../tests/fixtures';

// Installed frontend/client over an owned isolated service. Only synthetic GET
// observations are injected; no user task, source, mutation or model is executed.
for (const width of [390, 1672]) {
  test(`bounded GET recovery retains unknown task state at ${width}px`, async ({ page }, info) => {
    const origin = new URL(process.env.PATENTSAR_E2E_BASE_URL!);
    expect(['127.0.0.1', 'localhost', '[::1]']).toContain(origin.hostname);
    expect(Number(origin.port)).toBeGreaterThanOrEqual(18766);
    expect(Number(origin.port)).toBeLessThanOrEqual(18866);
    expect(process.env.PATENTSAR_E2E_RUN_JOBS).toBe('0');
    const projectId = process.env.PATENTSAR_E2E_SOURCE_PROJECT_ID!;
    const current = { ...job, id: 'controlled-read-poll-job', project_id: projectId };
    let mode: 'healthy' | 'transient' | 'offline' = 'healthy';
    let faults = 0;
    let handshakes = 0;
    let recoveredReads = 0;
    let releaseRecovery!: () => void;
    const holdRecovery = new Promise<void>((resolve) => (releaseRecovery = resolve));
    const writes: string[] = [];
    const errors: string[] = [];
    page.on('pageerror', (error) => errors.push(error.message));
    await page.route('**/api/v1/**', async (route) => {
      const request = route.request();
      const url = new URL(request.url());
      if (request.method() !== 'GET') {
        writes.push(url.pathname);
        return route.abort();
      }
      if (url.pathname === '/api/v1/session') handshakes++;
      const list = url.pathname === '/api/v1/jobs';
      const detail = url.pathname === `/api/v1/jobs/${current.id}`;
      if (detail && (mode === 'offline' || (mode === 'transient' && faults < 2))) {
        faults++;
        return route.fulfill({
          status: 503,
          contentType: 'application/json',
          body: JSON.stringify({
            error: {
              code: 'http_error',
              message: `Controlled task read unavailable (${faults})`,
            },
          }),
        });
      }
      if (detail && mode === 'transient') {
        recoveredReads++;
        await holdRecovery;
      }
      if (list || detail)
        return route.fulfill({
          status: 200,
          contentType: 'application/json',
          body: JSON.stringify(list ? { items: [current] } : current),
        });
      await route.continue();
    });

    try {
      await page.setViewportSize({ width, height: 940 });
      await page.goto(`/#/projects/${projectId}`);
      const cancel = page.getByRole('button', { name: /^(Cancel task|取消任务)$/ });
      await expect(cancel).toBeEnabled();
      const headerTop = () =>
        page.locator('.topbar').evaluate((element) => element.getBoundingClientRect().top);
      await expect.poll(headerTop).toBeGreaterThanOrEqual(0);
      const initialHandshakes = handshakes;
      mode = 'transient';
      await expect(page.getByRole('alert')).toContainText('Controlled task read unavailable');
      await expect(cancel).toBeDisabled();
      await expect(page.locator('.stage-current')).toHaveText('Stage status unknown');
      await expect.poll(() => recoveredReads).toBe(1);
      await expect(page.getByRole('button', { name: 'Run extraction', exact: true })).toHaveCount(
        0,
      );
      await page
        .getByRole('combobox', { name: 'Interface language', exact: true })
        .selectOption('zh-CN');
      await expect(page.locator('.stage-current')).toHaveText('阶段状态未知');
      await expect(cancel).toBeDisabled();
      await page.screenshot({
        path: info.outputPath('01-recovering-unknown.png'),
        animations: 'disabled',
      });
      await page.evaluate(() => {
        const sampling = window as Window & { headerRecoveryFrames?: Promise<number[]> };
        sampling.headerRecoveryFrames = new Promise((resolve) => {
          const positions: number[] = [];
          function observe() {
            positions.push(document.querySelector('.topbar')!.getBoundingClientRect().top);
            if (positions.length < 60) requestAnimationFrame(observe);
            else resolve(positions);
          }
          requestAnimationFrame(observe);
        });
      });
      releaseRecovery();
      mode = 'healthy';
      await expect(cancel).toBeEnabled();
      await expect(page.getByRole('alert')).toHaveCount(0);
      const recoveryPositions = await page.evaluate(async () => {
        const sampling = window as Window & { headerRecoveryFrames?: Promise<number[]> };
        if (!sampling.headerRecoveryFrames) throw new Error('Header sampling was not installed');
        return sampling.headerRecoveryFrames;
      });
      expect(Math.min(...recoveryPositions)).toBeGreaterThanOrEqual(0);
      expect(faults).toBe(2);
      expect(handshakes).toBe(initialHandshakes);
      await page.screenshot({
        path: info.outputPath('02-automatically-recovered.png'),
        animations: 'disabled',
      });

      // Four logical reads (initial plus three bounded recoveries), each with
      // the existing client's two gateway attempts. No further task operation.
      faults = 0;
      mode = 'offline';
      await expect.poll(() => faults, { timeout: 25000 }).toBe(8);
      await expect(page.getByRole('alert')).toContainText('Controlled task read unavailable (8)');
      await expect(cancel).toBeDisabled();
      await expect(page.locator('.stage-current')).toHaveText('阶段状态未知');
      await page.screenshot({
        path: info.outputPath('03-recovery-exhausted.png'),
        animations: 'disabled',
      });
      mode = 'healthy';
      await page.getByRole('alert').getByRole('button', { name: '重新加载', exact: true }).click();
      await expect(cancel).toBeEnabled();
      await expect(page.getByRole('alert')).toHaveCount(0);
      expect(
        await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth + 1),
      ).toBe(true);
      expect(handshakes).toBe(initialHandshakes);
      expect(errors).toEqual([]);
      expect(writes).toEqual([]);
    } finally {
      releaseRecovery();
    }
  });
}
