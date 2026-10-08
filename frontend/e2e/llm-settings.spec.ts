import { expect, test } from '@playwright/test';
import type { Page } from '@playwright/test';
import { decodeLLMSettings } from '../src/api/llmDecoders';
import type { LLMSettings, LLMSettingsUpdate } from '../src/api/llmTypes';

// No service is started here. The controller supplies a fresh, isolated native
// state/config with no overrides, patents or real model credentials. This string
// is deliberately not a usable provider key, and .invalid cannot be a provider.
const fixtureKey = 'synthetic-e2e-key-not-a-provider-credential';
const fixtureEndpoint = 'https://llm-fixture.invalid/v1';
const fixtureModel = 'synthetic-model';
const disclosure = '我同意向所选外部 API 发送有限的局部文字';
const settingsPath = '/api/v1/llm/settings';

async function readSettings(page: Page): Promise<LLMSettings> {
  const response = await page.request.get(settingsPath);
  expect(response.ok()).toBe(true);
  const raw: unknown = await response.json();
  const settings = decodeLLMSettings(raw); // rejects any credential-bearing field
  expect(JSON.stringify(raw)).not.toContain(fixtureKey);
  return settings;
}

async function saveFromUI(page: Page) {
  const saved = page.waitForResponse(
    (response) =>
      response.request().method() === 'PUT' && new URL(response.url()).pathname === settingsPath,
  );
  await page
    .getByRole('dialog', { name: 'LLM API 设置' })
    .getByRole('button', { name: '保存', exact: true })
    .click();
  const response = await saved;
  expect(response.status()).toBe(200);
  expect(response.request().headers()['x-csrf-token']).toBeTruthy();
  const result = decodeLLMSettings(await response.json());
  await expect(page.getByLabel('API 密钥', { exact: true })).toHaveValue('');
  await expect(page.getByText('设置已保存。', { exact: true })).toBeVisible();
  return { result, request: response.request().postDataJSON() as LLMSettingsUpdate };
}

async function reopen(page: Page) {
  await page.reload();
  const panel = page.getByRole('region', { name: 'LLM API', exact: true });
  await expect(panel.getByRole('button', { name: '配置', exact: true })).toBeEnabled();
  await panel.getByRole('button', { name: '配置', exact: true }).click();
  await expect(
    page.getByText('设置变更仅影响后续新任务；续跑沿用原配置快照与剩余调用配额。', { exact: true }),
  ).toBeVisible();
  return page.getByRole('dialog', { name: 'LLM API 设置', exact: true });
}

async function expectNoOverflow(page: Page) {
  const dimensions = await page.evaluate(() => {
    const dialog = document.querySelector<HTMLDialogElement>('.llm-settings-dialog');
    const body = dialog?.querySelector<HTMLElement>('.dialog-body');
    const bounds = dialog?.getBoundingClientRect();
    return {
      document: document.documentElement.scrollWidth <= innerWidth + 1,
      body: Boolean(body && body.scrollWidth <= body.clientWidth + 1),
      dialog: Boolean(
        bounds &&
        bounds.left >= 0 &&
        bounds.right <= innerWidth &&
        bounds.top >= 0 &&
        bounds.bottom <= innerHeight + 1,
      ),
    };
  });
  expect(dimensions).toEqual({ document: true, body: true, dialog: true });
}

test('isolated native settings persist, redact keys, require consent and remain accessible at 390/800/1672 without a provider call', async ({
  page,
}, testInfo) => {
  test.skip(
    process.env.PATENTSAR_E2E_ALLOW_LLM_SETTINGS !== 'isolated-state' ||
      process.env.PATENTSAR_E2E_LLM_FIXTURE !== 'empty-synthetic',
    'Requires explicit write authority and fresh empty-synthetic native state/config, never production.',
  );
  const target = process.env.PATENTSAR_E2E_BASE_URL;
  expect(target, 'Controller must name the isolated loopback service explicitly').toBeTruthy();
  const origin = new URL(target!);
  expect(['127.0.0.1', 'localhost', '[::1]']).toContain(origin.hostname);
  expect(
    ['', '8765', '8766', '18765'],
    'Never use default or workstation production ports',
  ).not.toContain(origin.port);
  const evidenceRoot = process.env.PATENTSAR_E2E_OUTPUT_DIR ?? '';
  const runnerRoot = process.env.RUNNER_TEMP ?? '';
  const isolatedCI =
    process.env.GITHUB_ACTIONS === 'true' &&
    runnerRoot.startsWith('/') &&
    evidenceRoot.startsWith(`${runnerRoot}/`) &&
    !evidenceRoot.split('/').includes('..');
  expect(
    evidenceRoot.startsWith('/srv/wsl/') || isolatedCI,
    'Local evidence stays on E; controlled CI evidence stays in its isolated runner temp root',
  ).toBe(true);

  const consoleErrors: string[] = [];
  const pageErrors: string[] = [];
  const testRequests: string[] = [];
  const externalRequests: string[] = [];
  page.on('console', (message) => {
    if (message.type() === 'error') consoleErrors.push(message.text());
  });
  page.on('pageerror', (error) => pageErrors.push(error.message));
  // Safety tripwire only, never a mocked successful response. The test cancels
  // every confirmation; native synthetic transport proof belongs to the parent.
  await page.route('**/api/v1/llm/test', async (route) => {
    testRequests.push(route.request().method());
    await route.abort('blockedbyclient');
  });
  await page.route('**/*', async (route) => {
    const url = new URL(route.request().url());
    if (['http:', 'https:'].includes(url.protocol) && url.origin !== origin.origin) {
      externalRequests.push(url.origin);
      await route.abort('blockedbyclient');
    } else await route.fallback();
  });

  await page.goto('/#/settings');
  // Wait for the real SPA session and settings load; request contexts do not
  // create a session independently and must not race the bootstrap cookie.
  await expect(
    page
      .getByRole('region', { name: 'LLM API', exact: true })
      .getByRole('button', { name: '配置', exact: true }),
  ).toBeEnabled();
  const before = await readSettings(page);
  expect(before).toMatchObject({
    revision: 0,
    endpoint: '',
    model: '',
    protocol: 'openai-compatible',
    response_mode: 'json-schema',
    mode: 'off',
    data_consent: false,
    key_configured: false,
    editable: true,
    status: 'disabled',
    last_test: null,
  });
  const panel = page.getByRole('region', { name: 'LLM API', exact: true });
  await expect(panel.getByLabel('LLM API 状态')).toHaveText('已关闭');
  await expect(page.getByText('仅外部 API，不在本机部署模型', { exact: true })).toHaveCount(1);
  await panel.getByRole('button', { name: '配置', exact: true }).click();
  await expect(page.getByLabel('HTTPS API 基础地址', { exact: true })).toBeFocused();
  await page.getByLabel('HTTPS API 基础地址', { exact: true }).fill(fixtureEndpoint);
  await page.getByLabel('模型', { exact: true }).fill(fixtureModel);
  await page.getByLabel('清除密钥并关闭', { exact: true }).check();
  const off = await saveFromUI(page);
  expect(off.request).toEqual({
    expected_revision: 0,
    endpoint: fixtureEndpoint,
    model: fixtureModel,
    protocol: 'openai-compatible',
    response_mode: 'json-schema',
    mode: 'off',
    data_consent: false,
    api_key: '',
  });
  expect(off.result).toMatchObject({ mode: 'off', key_configured: false, status: 'disabled' });

  let dialog = await reopen(page);
  await expect(dialog.getByLabel('HTTPS API 基础地址', { exact: true })).toHaveValue(
    fixtureEndpoint,
  );
  await expect(dialog.getByLabel('模型', { exact: true })).toHaveValue(fixtureModel);
  await expect(dialog.getByLabel('API 协议', { exact: true })).toHaveValue('openai-compatible');
  await expect(dialog.getByLabel('复核模式', { exact: true })).toHaveValue('off');
  await expect(dialog.getByRole('button', { name: '测试接口', exact: true })).toHaveCount(0);
  const persisted = await readSettings(page);
  expect(persisted).toMatchObject({
    revision: off.result.revision,
    endpoint: fixtureEndpoint,
    model: fixtureModel,
    mode: 'off',
    key_configured: false,
  });

  // Local validation is not a fake successful backend response.
  await dialog.getByLabel('复核模式', { exact: true }).selectOption('on-error');
  await expect(dialog.getByRole('button', { name: '保存', exact: true })).toBeDisabled();
  await dialog.getByLabel(disclosure, { exact: true }).check();
  await dialog.getByRole('button', { name: '保存', exact: true }).click();
  await expect(dialog.getByRole('alert')).toContainText('启用前请填写');

  const session = await page.request.get('/api/v1/session');
  expect(session.ok()).toBe(true);
  const csrf: unknown = ((await session.json()) as { csrf_token: unknown }).csrf_token;
  expect(typeof csrf).toBe('string');
  const headers = { Origin: origin.origin, 'X-CSRF-Token': csrf as string };
  const invalid = await page.request.put(settingsPath, {
    headers,
    data: {
      expected_revision: persisted.revision,
      endpoint: fixtureEndpoint,
      model: fixtureModel,
      protocol: 'openai-compatible',
      response_mode: 'json-schema',
      mode: 'on-error',
      data_consent: false,
      api_key: fixtureKey,
    },
  });
  expect(invalid.status()).toBe(422);
  expect(await invalid.text()).not.toContain(fixtureKey);
  expect((await readSettings(page)).revision).toBe(persisted.revision);

  await dialog.getByLabel('API 密钥', { exact: true }).fill(fixtureKey);
  const enabled = await saveFromUI(page);
  expect(enabled.request).toMatchObject({
    expected_revision: persisted.revision,
    mode: 'on-error',
    data_consent: true,
    api_key: fixtureKey,
  });
  expect(enabled.result).toMatchObject({ status: 'ready', key_configured: true, mode: 'on-error' });
  await expect(panel.getByLabel('LLM API 状态')).toHaveText('已配置');
  await expect(page.getByText('接口测试通过。', { exact: true })).toHaveCount(0);
  await dialog.getByRole('button', { name: '测试接口', exact: true }).click();
  const confirmation = page.getByRole('dialog', { name: '确认接口测试', exact: true });
  await expect(confirmation).toContainText('固定的合成文本');
  await expect(confirmation).toContainText('可能产生 API 费用');
  await expect(confirmation.getByRole('button', { name: '取消测试', exact: true })).toBeFocused();
  await page.keyboard.press('Escape');
  await expect(confirmation).toHaveCount(0);
  await expect(dialog.getByRole('button', { name: '测试接口', exact: true })).toBeFocused();
  expect(testRequests).toEqual([]);

  await dialog.getByLabel('复核模式', { exact: true }).selectOption('quality');
  await expect(dialog.getByRole('button', { name: '测试接口', exact: true })).toBeDisabled();
  const quality = await saveFromUI(page);
  expect(quality.request).not.toHaveProperty('api_key');
  expect(quality.result).toMatchObject({ mode: 'quality', status: 'ready', key_configured: true });
  dialog = await reopen(page);
  await expect(dialog.getByLabel('复核模式', { exact: true })).toHaveValue('quality');
  await expect(dialog.getByLabel('API 密钥', { exact: true })).toHaveValue('');
  const leaked = await page.evaluate(
    (key) =>
      [localStorage, sessionStorage].some((storage) =>
        Array.from({ length: storage.length }, (_, index) =>
          storage.getItem(storage.key(index)!),
        ).some((value) => value?.includes(key)),
      ),
    fixtureKey,
  );
  expect(leaked, 'Synthetic credential must never be persisted in browser storage').toBe(false);
  expect(page.url()).not.toContain(fixtureKey);

  await dialog.getByText('响应格式', { exact: true }).click();
  await dialog.getByLabel('JSON 格式', { exact: true }).selectOption('json-object');
  const jsonMode = await saveFromUI(page);
  expect(jsonMode.request).not.toHaveProperty('api_key');
  expect(jsonMode.result.response_mode).toBe('json-object');
  for (const protocol of ['anthropic', 'gemini', 'openai-compatible']) {
    await dialog.getByLabel('API 协议', { exact: true }).selectOption(protocol);
    await dialog.getByRole('button', { name: '保存', exact: true }).click();
    await expect(dialog.getByRole('alert')).toContainText('地址、模型或协议已改变');
    await dialog.getByLabel('API 密钥', { exact: true }).fill(fixtureKey);
    const protocolSaved = await saveFromUI(page);
    expect(protocolSaved.result).toMatchObject({
      protocol,
      response_mode: 'json-schema',
      status: 'ready',
      key_configured: true,
    });
    expect(protocolSaved.request).toHaveProperty('api_key', fixtureKey);
    dialog = await reopen(page);
    await expect(dialog.getByLabel('API 协议', { exact: true })).toHaveValue(protocol);
    await expect(dialog.getByLabel('API 密钥', { exact: true })).toHaveValue('');
    if (protocol !== 'openai-compatible')
      await expect(dialog.getByText('响应格式', { exact: true })).toHaveCount(0);
  }
  await dialog.getByText('响应格式', { exact: true }).click();
  await dialog.getByLabel('JSON 格式', { exact: true }).selectOption('prompt-only');
  const promptMode = await saveFromUI(page);
  expect(promptMode.request).not.toHaveProperty('api_key');
  expect(promptMode.result.response_mode).toBe('prompt-only');

  await dialog.getByLabel('模型', { exact: true }).fill('changed-synthetic-model');
  await dialog.getByRole('button', { name: '保存', exact: true }).click();
  await expect(dialog.getByRole('alert')).toContainText('地址、模型或协议已改变');
  await dialog.getByLabel('清除密钥并关闭', { exact: true }).check();
  const cleared = await saveFromUI(page);
  expect(cleared.request).toMatchObject({
    model: 'changed-synthetic-model',
    mode: 'off',
    data_consent: false,
    api_key: '',
  });
  expect(cleared.result).toMatchObject({ mode: 'off', key_configured: false, status: 'disabled' });
  const conflict = await page.request.put(settingsPath, {
    headers,
    data: {
      expected_revision: persisted.revision,
      endpoint: fixtureEndpoint,
      model: 'changed-synthetic-model',
      protocol: 'openai-compatible',
      response_mode: 'prompt-only',
      mode: 'off',
      data_consent: false,
      api_key: '',
    },
  });
  expect(conflict.status()).toBe(409);
  expect(await conflict.text()).not.toContain(fixtureKey);

  for (const width of [390, 800, 1672]) {
    await page.setViewportSize({ width, height: 942 });
    dialog = await reopen(page);
    await expect(dialog.getByLabel('HTTPS API 基础地址', { exact: true })).toBeFocused();
    await expect(dialog.getByLabel('复核模式', { exact: true })).toHaveValue('off');
    await expect(dialog.getByLabel('模型', { exact: true })).toHaveValue('changed-synthetic-model');
    await expect(dialog.getByLabel('API 密钥', { exact: true })).toHaveValue('');
    await expect(dialog.getByRole('button', { name: '测试接口', exact: true })).toHaveCount(0);
    await expectNoOverflow(page);
    const close = dialog.getByRole('button', { name: '关闭对话框', exact: true });
    const cancel = dialog.getByRole('button', { name: '取消', exact: true });
    await cancel.focus();
    await page.keyboard.press('Tab');
    await expect(close).toBeFocused();
    await page.keyboard.press('Shift+Tab');
    await expect(cancel).toBeFocused();
    await page.screenshot({
      path: testInfo.outputPath(`llm-settings-${width}.png`),
      fullPage: true,
    });
    await page.keyboard.press('Escape');
    await expect(dialog).toHaveCount(0);
    await expect(panel.getByRole('button', { name: '配置', exact: true })).toBeFocused();
    await expectNoOverflowAfterClose(page);
  }
  const final = await readSettings(page);
  expect(final).toMatchObject({
    revision: cleared.result.revision,
    mode: 'off',
    key_configured: false,
    last_test: null,
  });
  expect(testRequests, 'No /llm/test request may be dispatched by this browser test').toEqual([]);
  expect(externalRequests, 'Browser must never directly contact an external provider').toEqual([]);
  expect(pageErrors).toEqual([]);
  expect(consoleErrors).toEqual([]);
});

async function expectNoOverflowAfterClose(page: Page) {
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth + 1)).toBe(
    true,
  );
}
