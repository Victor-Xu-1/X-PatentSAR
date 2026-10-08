import { expect, test } from '@playwright/test';
import type { Page } from '@playwright/test';
import react from '@vitejs/plugin-react';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { fileURLToPath } from 'node:url';
import { createServer } from 'vite';
import type { ViteDevServer } from 'vite';
import { authorizedJob, recoveryJob, recoverySettings } from '../tests/llm-recovery-fixtures';
import { session } from '../tests/fixtures';

// Pure UI/transport verification, not backend or scientific acceptance. Only a
// disposable frontend fixture server is started, never the running WSL service.
let fixtureServer: ViteDevServer;
let origin: string;
test.beforeAll(async () => {
  fixtureServer = await createServer({
    configFile: false,
    root: fileURLToPath(new URL('../', import.meta.url)),
    cacheDir: join(
      process.env.PATENTSAR_FRONTEND_CACHE_DIR ??
        (process.env.CI
          ? join(process.env.RUNNER_TEMP ?? tmpdir(), 'patentsar-llm-recovery-ui')
          : '/srv/wsl/cache/patentsar-llm-recovery-ui'),
      `browser-${process.pid}`,
    ),
    plugins: [react()],
    optimizeDeps: {
      noDiscovery: true,
      include: ['react', 'react-dom/client', 'react/jsx-runtime', 'lucide-react'],
    },
    server: { host: '127.0.0.1', port: 0, strictPort: true },
  });
  await fixtureServer.listen();
  const address = fixtureServer.httpServer?.address();
  if (!address || typeof address === 'string') throw new Error('Missing isolated fixture address');
  origin = `http://127.0.0.1:${address.port}`;
});
test.afterAll(async () => {
  await fixtureServer?.close();
});

async function transport(page: Page, failure?: 'conflict' | 'uncertain', syntheticFailure = false) {
  const writes: { path: string; body: unknown }[] = [];
  const reads: string[] = [];
  const unexpected: string[] = [];
  let updated = false;
  let conflicted = false;
  await page.route('**/*', async (route) => {
    const request = route.request();
    const url = new URL(request.url());
    if (url.origin !== origin) {
      unexpected.push('external request');
      await route.abort('blockedbyclient');
      return;
    }
    if (url.pathname === '/favicon.ico') {
      await route.fulfill({ status: 204 });
      return;
    }
    if (!url.pathname.startsWith('/api/')) {
      await route.continue();
      return;
    }
    if (request.method() === 'GET') reads.push(url.pathname);
    else writes.push({ path: url.pathname, body: request.postDataJSON() });
    const fulfill = (body: unknown, status = 200) => route.fulfill({ status, json: body });
    if (url.pathname === '/api/v1/session' && request.method() === 'GET') {
      await fulfill(session);
      return;
    }
    if (url.pathname === '/api/v1/llm/settings' && request.method() === 'GET') {
      await fulfill({
        ...recoverySettings,
        revision: conflicted ? 18 : 17,
        endpoint: `https://recovery-fixture.invalid/${'long-path-'.repeat(16)}`,
        model: 'synthetic-model-'.repeat(8),
        last_test: syntheticFailure
          ? {
              status: 'failed',
              reason: 'invalid_response',
              settings_revision: 17,
              checked_at: '2026-10-08T00:00:00Z',
            }
          : null,
      });
      return;
    }
    if (
      url.pathname === `/api/v1/jobs/${recoveryJob.id}/llm-authorization` &&
      request.method() === 'POST'
    ) {
      expect(request.headers()['x-csrf-token']).toBe(session.csrf_token);
      expect(request.postDataJSON()).toEqual({ expected_revision: 17, consent: true });
      if (failure === 'uncertain') {
        await route.abort('connectionfailed');
        return;
      }
      if (failure === 'conflict') {
        conflicted = true;
        await fulfill(
          {
            error: {
              code: 'llm_authorization_changed',
              message: 'synthetic-sensitive-provider-error',
            },
          },
          409,
        );
        return;
      }
      updated = true;
      await fulfill(authorizedJob);
      return;
    }
    if (url.pathname === `/api/v1/jobs/${recoveryJob.id}` && request.method() === 'GET') {
      await fulfill(updated ? authorizedJob : recoveryJob);
      return;
    }
    unexpected.push(`${request.method()} ${url.pathname}`);
    await route.abort('blockedbyclient');
  });
  return { writes, reads, unexpected };
}

async function noOverflow(page: Page) {
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth + 1)).toBe(
    true,
  );
  for (const dialog of await page.locator('dialog[open]').all()) {
    expect(await dialog.evaluate((element) => element.scrollWidth <= element.clientWidth + 1)).toBe(
      true,
    );
    const box = await dialog.boundingBox();
    expect(box?.x).toBeGreaterThanOrEqual(0);
    expect((box?.x ?? 0) + (box?.width ?? 0)).toBeLessThanOrEqual(page.viewportSize()!.width + 1);
  }
}

for (const width of [390, 800, 1672]) {
  test(`isolated recovery consent/cancel/success at ${width}px without model or auto-resume`, async ({
    page,
  }, info) => {
    const errors: string[] = [];
    page.on('pageerror', (error) => errors.push(error.message));
    const protocol = await transport(page);
    await page.setViewportSize({ width, height: 942 });
    await page.goto(`${origin}/e2e/llm-recovery.fixture.html`);
    await expect(page.getByRole('region', { name: 'LLM 局部修复' })).toBeHidden();
    expect(protocol.reads).toEqual([]);
    await page.locator('summary[aria-label="任务详情"]').click();
    await expect(page.getByRole('region', { name: 'LLM 局部修复' })).toContainText('剩余调用 3 次');
    await expect(page.getByRole('link', { name: '配置 LLM API' })).toHaveAttribute(
      'href',
      '#/settings',
    );
    await page.locator('.stage-observation summary').filter({ hasText: '编号绑定' }).click();
    await expect(page.getByText('来源区域 7 · 待修复 2')).toBeVisible();
    await noOverflow(page);
    await page.getByRole('button', { name: '更新 API 授权' }).click();
    let dialog = page.getByRole('dialog', { name: '更新此任务的 API 授权？' });
    await expect(dialog.getByRole('button', { name: '确认更新授权' })).toBeEnabled();
    await expect(dialog.getByRole('button', { name: '取消', exact: true })).toBeFocused();
    await expect(dialog).toContainText('不重置配额、不开始提取、不调用模型');
    expect(
      await dialog
        .locator('.job-dates')
        .evaluate((element) => getComputedStyle(element).gridTemplateColumns.split(' ').length),
    ).toBe(width <= 760 ? 1 : 3);
    await noOverflow(page);
    await page.screenshot({
      path: info.outputPath(`recovery-consent-${width}.png`),
      fullPage: true,
    });
    await dialog.getByRole('button', { name: '确认更新授权' }).focus();
    await page.keyboard.press('Tab');
    await expect(dialog.getByRole('button', { name: '关闭对话框' })).toBeFocused();
    await page.keyboard.press('Escape');
    await expect(dialog).toHaveCount(0);
    await expect(page.getByRole('button', { name: '更新 API 授权' })).toBeFocused();
    expect(protocol.writes).toEqual([]);
    await page.getByRole('button', { name: '更新 API 授权' }).click();
    dialog = page.getByRole('dialog', { name: '更新此任务的 API 授权？' });
    await dialog.getByRole('button', { name: '确认更新授权' }).click();
    await expect(dialog).toHaveCount(0);
    await expect(
      page.getByText('API 授权已更新，未开始提取。核对后可手动继续提取。'),
    ).toBeVisible();
    await expect(page.getByRole('button', { name: '继续提取' })).toBeEnabled();
    await expect(page.getByRole('button', { name: '更新 API 授权' })).toHaveCount(0);
    expect(protocol.writes).toHaveLength(1);
    expect(protocol.reads.filter((path) => path.endsWith('/llm/settings'))).toHaveLength(2);
    expect(protocol.unexpected).toEqual([]);
    expect(errors).toEqual([]);
    await noOverflow(page);
  });
}

for (const failure of ['conflict', 'uncertain'] as const) {
  test(`isolated ${failure} write requires explicit refresh, never replays`, async ({ page }) => {
    const protocol = await transport(page, failure);
    await page.setViewportSize({ width: 390, height: 844 });
    await page.goto(`${origin}/e2e/llm-recovery.fixture.html`);
    await page.locator('summary[aria-label="任务详情"]').click();
    await page.getByRole('button', { name: '更新 API 授权' }).click();
    const dialog = page.getByRole('dialog', { name: '更新此任务的 API 授权？' });
    await dialog.getByRole('button', { name: '确认更新授权' }).click();
    await expect(dialog.getByRole('alert')).toContainText(
      failure === 'conflict' ? '配置或授权已改变' : '写入结果尚未确认',
    );
    await expect(dialog.getByRole('button', { name: '确认更新授权' })).toHaveCount(0);
    await expect(dialog).not.toContainText('synthetic-sensitive-provider-error');
    await noOverflow(page);
    await dialog.getByRole('button', { name: '取消', exact: true }).click();
    await expect(page.getByRole('button', { name: '继续提取' })).toBeDisabled();
    await page.getByRole('button', { name: '刷新核对任务与配置' }).click();
    await expect(page.getByRole('button', { name: '更新 API 授权' })).toBeEnabled();
    await page.getByRole('button', { name: '更新 API 授权' }).click();
    await expect(dialog.getByRole('button', { name: '确认更新授权' })).toBeEnabled();
    expect(protocol.writes).toHaveLength(1);
    expect(protocol.unexpected).toEqual([]);
  });
}

test('isolated compact workbench has one short blocked hint and nested dialogs at 390px', async ({
  page,
}, info) => {
  const protocol = await transport(page);
  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto(`${origin}/e2e/llm-recovery.fixture.html?compact`);
  await expect(page.getByText('API 待核对', { exact: true })).toBeVisible();
  await expect(page.getByText(/剩余调用/)).toHaveCount(0);
  await noOverflow(page);
  await page.getByRole('button', { name: '任务详情', exact: true }).click();
  const details = page.getByRole('dialog', { name: '任务详情', exact: true });
  await expect(details).toContainText('剩余调用 3 次');
  await details.getByRole('button', { name: '更新 API 授权' }).click();
  const confirmation = page.getByRole('dialog', { name: '更新此任务的 API 授权？', exact: true });
  await expect(confirmation.getByRole('button', { name: '确认更新授权' })).toBeEnabled();
  await noOverflow(page);
  await page.screenshot({ path: info.outputPath('compact-recovery-390.png'), fullPage: true });
  await page.keyboard.press('Escape');
  await expect(confirmation).toHaveCount(0);
  await expect(details.getByRole('button', { name: '更新 API 授权' })).toBeFocused();
  await page.keyboard.press('Escape');
  await expect(details).toHaveCount(0);
  await expect(page.getByRole('button', { name: '任务详情', exact: true })).toBeFocused();
  expect(protocol.writes).toEqual([]);
  expect(protocol.unexpected).toEqual([]);
});

test('isolated narrow settings shows actionable nonce failure, not scientific readiness', async ({
  page,
}) => {
  const protocol = await transport(page, undefined, true);
  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto(`${origin}/e2e/llm-recovery.fixture.html?view=settings`);
  await page.getByRole('button', { name: '配置', exact: true }).click();
  const dialog = page.getByRole('dialog', { name: 'LLM API 设置' });
  await expect(dialog).toContainText('接口未正确返回随机验证样本，请检查协议及 JSON 响应格式。');
  await expect(dialog).toContainText('已配置不等于模型可用');
  await noOverflow(page);
  expect(protocol.writes).toEqual([]);
  expect(protocol.unexpected).toEqual([]);
});
