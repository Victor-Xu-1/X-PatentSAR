import { expect, test } from '@playwright/test';
import type { Page } from '@playwright/test';
import {
  decodeEnvironmentCatalog,
  decodeEnvironmentOperation,
  decodeEnvironmentRequest,
  matchesEnvironmentRequest,
} from '../src/api/environmentDecoders';
import { environmentSetupComponents } from '../src/model/environmentSetup';
import { isEnvironmentComponentReady } from '../src/model/environmentStatus';

async function catalogFromServer(page: Page) {
  const response = await page.request.get('/api/v1/environments');
  expect(response.ok()).toBe(true);
  return decodeEnvironmentCatalog(await response.json());
}

// Opt-in only: the controller must provide an isolated configuration/state with a genuine missing component.
test('owned complete setup submits one six-component operation and becomes verified-ready after reload', async ({
  page,
}, testInfo) => {
  test.setTimeout(660_000);
  test.skip(
    process.env.PATENTSAR_E2E_ENV_COMPLETE_SETUP !== 'isolated-state',
    'Requires explicitly owned non-production setup state; may download pinned official resources.',
  );
  await page.goto('/#/settings');
  await expect(page.getByRole('heading', { name: '完整运行环境', exact: true })).toBeVisible();
  const before = await catalogFromServer(page);
  const plan = environmentSetupComponents(before);
  expect(before.settings.enabled).toBe(true);
  expect(before.active_operation).toBeNull();
  expect(plan.every(isEnvironmentComponentReady)).toBe(false);
  expect(
    plan.some(
      (component) => component.presence === 'missing' || component.presence === 'unconfigured',
    ),
    'Controlled cold setup must have a genuinely missing component',
  ).toBe(true);
  await page.screenshot({ path: testInfo.outputPath('minimal-initial.png'), fullPage: true });
  const writes: string[] = [];
  page.on('request', (request) => {
    if (request.method() !== 'GET' && request.url().includes('/api/v1/environments'))
      writes.push(request.url());
  });
  await page.getByRole('button', { name: '一键部署全部环境', exact: true }).click();
  const dialog = page.getByRole('dialog');
  await expect(dialog.locator('[data-install-component]')).toHaveCount(plan.length);
  for (const component of plan) {
    const entry = dialog.locator('[data-install-component="' + component.id + '"]');
    await expect(entry).toContainText(component.version);
    await expect(entry).toContainText(component.license);
  }
  const confirm = dialog.getByRole('button', { name: '确认下载并安装', exact: true });
  await expect(confirm).toBeDisabled();
  await page.screenshot({ path: testInfo.outputPath('minimal-consent.png'), fullPage: true });
  await dialog.getByRole('checkbox').check();
  const createdResponse = page.waitForResponse(
    (value) =>
      value.request().method() === 'POST' &&
      value.url().endsWith('/api/v1/environments/operations'),
  );
  await confirm.click();
  const created = await createdResponse;
  expect(created.status()).toBe(202);
  expect(created.request().headers()['x-csrf-token']).toBeTruthy();
  const payload = created.request().postDataJSON() as Record<string, unknown>;
  const request = decodeEnvironmentRequest(payload);
  expect(request).toMatchObject({
    action: 'install',
    component_ids: before.setup_component_ids,
    expected_revision: before.settings.revision,
  });
  expect(Object.keys(payload).sort()).toEqual([
    'action',
    'component_ids',
    'expected_revision',
    'request_id',
  ]);
  // Navigation can invalidate the browser's POST response body. Reconcile the durable
  // write by request identity using GET only; never replay an accepted installation.
  const accepted = await catalogFromServer(page);
  const found = [accepted.active_operation, ...accepted.operations].find(
    (operation) => operation?.request_id === request.request_id,
  );
  expect(found, 'Accepted install must exist in the authenticated durable catalog').toBeTruthy();
  const operation = decodeEnvironmentOperation(found);
  expect(matchesEnvironmentRequest(operation, request)).toBe(true);
  expect(operation.request_id).toBe(request.request_id);
  expect(operation.component_ids).toEqual(before.setup_component_ids);
  expect(operation.install_root).toBe(before.settings.install_root);
  await expect
    .poll(
      async () => {
        const read = await page.request.get(
          '/api/v1/environments/operations/' + encodeURIComponent(operation.id),
        );
        expect(read.ok()).toBe(true);
        return decodeEnvironmentOperation(await read.json()).status;
      },
      { timeout: 600_000, intervals: [1000, 2000, 5000] },
    )
    .toBe('complete');
  const finishedResponse = await page.request.get(
    '/api/v1/environments/operations/' + encodeURIComponent(operation.id),
  );
  const finished = decodeEnvironmentOperation(await finishedResponse.json());
  expect(finished.applied).toBe(true);
  await page.reload();
  await expect(page.getByRole('button', { name: '环境已就绪', exact: true })).toBeDisabled();
  await expect(page.getByRole('button', { name: '重新检测', exact: true })).toBeEnabled();
  await expect(
    page.locator('[data-component], .environment-history, .environment-log, .runtime-diagnostics'),
  ).toHaveCount(0);
  const after = await catalogFromServer(page);
  expect(after.setup_component_ids).toEqual(before.setup_component_ids);
  expect(after.components.every(isEnvironmentComponentReady)).toBe(true);
  expect(writes, 'Consent and reload must cause one install only').toHaveLength(1);
  await testInfo.attach('complete-environment-setup', {
    body: JSON.stringify({ request, operation: finished, catalog: after, writes }),
    contentType: 'application/json',
  });
  await page.screenshot({ path: testInfo.outputPath('minimal-ready.png'), fullPage: true });
});
