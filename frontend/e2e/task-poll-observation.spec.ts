import { expect, test } from '@playwright/test';
import { job } from '../tests/fixtures';

// Synthetic task DTOs over an installed service; no task writes or model work.
for (const width of [390, 1672]) {
  test(`routine polls retain confirmed progress but never task-write authority at ${width}`, async ({
    page,
  }, info) => {
    const origin = new URL(process.env.PATENTSAR_E2E_BASE_URL!);
    expect(['127.0.0.1', 'localhost', '[::1]']).toContain(origin.hostname);
    expect(Number(origin.port)).toBeGreaterThanOrEqual(18766);
    expect(Number(origin.port)).toBeLessThanOrEqual(18866);
    expect(process.env.PATENTSAR_E2E_RUN_JOBS).toBe('0');
    const projectId = process.env.PATENTSAR_E2E_SOURCE_PROJECT_ID!;
    const current = { ...job, id: 'controlled-poll-observation', project_id: projectId };
    let mode: 'healthy' | 'blocked' | 'denied' = 'healthy';
    const releases: (() => void)[] = [];
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
      if (url.pathname === '/api/v1/jobs') return route.fulfill({ json: { items: [current] } });
      if (url.pathname === `/api/v1/jobs/${current.id}`) {
        if (mode === 'blocked') await new Promise<void>((resolve) => releases.push(resolve));
        if (mode === 'denied')
          return route.fulfill({
            status: 401,
            json: {
              error: { code: 'session_required', message: 'Controlled source read unavailable' },
            },
          });
        return route.fulfill({ json: current });
      }
      return route.continue();
    });
    try {
      await page.setViewportSize({ width, height: 940 });
      await page.goto(`/#/projects/${projectId}`);
      const cancel = page.getByRole('button', { name: 'Cancel task', exact: true });
      await expect(cancel).toBeEnabled();
      mode = 'blocked';
      await expect.poll(() => releases.length, { timeout: 10000 }).toBeGreaterThan(0);
      await expect(cancel).toBeDisabled();
      await expect(page.locator('.stage-current')).not.toContainText('unknown');
      await page.getByRole('button', { name: 'Task details', exact: true }).click();
      let dialog = page.getByRole('dialog', { name: 'Task details', exact: true });
      await expect(dialog).toContainText(current.id);
      await expect(dialog).not.toContainText('Stage status unknown');
      await page.screenshot({ path: info.outputPath('01-confirmed-pending-read-en.png') });
      await dialog.getByRole('button', { name: 'Close dialog', exact: true }).click();
      await page
        .getByRole('combobox', { name: 'Interface language', exact: true })
        .selectOption('zh-CN');
      await page.getByRole('button', { name: '任务详情', exact: true }).click();
      dialog = page.getByRole('dialog', { name: '任务详情', exact: true });
      await expect(dialog).not.toContainText('阶段状态未知');
      await page.screenshot({ path: info.outputPath('02-confirmed-pending-read-zh.png') });
      await dialog.getByRole('button', { name: '关闭对话框', exact: true }).click();
      mode = 'denied';
      releases.splice(0).forEach((release) => release());
      await expect(page.getByRole('alert')).toContainText('Controlled source read unavailable');
      await expect(page.locator('.stage-current')).toHaveText('阶段状态未知');
      await expect(page.getByRole('button', { name: '取消任务', exact: true })).toBeDisabled();
      mode = 'healthy';
      await page.getByRole('alert').getByRole('button', { name: '重新加载', exact: true }).click();
      await expect(page.getByRole('button', { name: '取消任务', exact: true })).toBeEnabled();
      await expect(page.getByRole('alert')).toHaveCount(0);
      await expect(page.locator('.stage-current')).not.toContainText('阶段状态未知');
      expect(
        await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth + 1),
      ).toBe(true);
      expect(writes).toEqual([]);
      expect(errors).toEqual([]);
    } finally {
      mode = 'healthy';
      releases.splice(0).forEach((release) => release());
    }
  });
}
