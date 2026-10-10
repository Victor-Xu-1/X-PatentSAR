import { expect, test } from '@playwright/test';
import type { Page } from '@playwright/test';
import { setLocale } from '../src/i18n';
import {
  decodeEnvironmentCatalog,
  decodeEnvironmentOperation,
} from '../src/api/environmentDecoders';
import { activeEnvironmentOperation } from '../src/model/environment';
import { canSetupEnvironmentPlan, environmentSetupComponents } from '../src/model/environmentSetup';
import {
  environmentComponentBadge,
  isEnvironmentComponentReady,
} from '../src/model/environmentStatus';

setLocale('zh-CN');
test.beforeEach(async ({ page }) => {
  await page.goto('/#/settings');
  await page
    .getByRole('combobox', { name: 'Interface language', exact: true })
    .selectOption('zh-CN');
});

async function catalogFromServer(page: Page) {
  const response = await page.request.get('/api/v1/environments');
  expect(response.ok()).toBe(true);
  return decodeEnvironmentCatalog(await response.json());
}
for (const viewport of [
  { width: 1672, height: 942 },
  { width: 1280, height: 800 },
  { width: 390, height: 844 },
]) {
  test(
    'real compact environment overview and complete consent at ' +
      viewport.width +
      'x' +
      viewport.height,
    async ({ page }) => {
      const errors: string[] = [],
        writes: string[] = [];
      page.on('pageerror', (error) => errors.push(error.message));
      page.on('request', (request) => {
        if (request.method() !== 'GET' && request.url().includes('/api/v1/environments'))
          writes.push(request.url());
      });
      await page.setViewportSize(viewport);
      await page.goto('/#/settings');
      await expect(page.getByRole('heading', { name: '完整运行环境', exact: true })).toBeVisible();
      const catalog = await catalogFromServer(page);
      await expect(page.getByRole('dialog')).toHaveCount(0);
      await expect(
        page.locator(
          '[data-component], .environment-log, .environment-history, .runtime-diagnostics',
        ),
      ).toHaveCount(0);
      await expect(page.locator('.environment-page')).not.toContainText(
        catalog.settings.install_root,
      );
      expect(
        await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth + 2),
      ).toBe(true);
      if (viewport.width >= 760 && !activeEnvironmentOperation(catalog.active_operation))
        expect(
          await page.locator('.environment-page').evaluate((node) => {
            // The management shell stretches to the viewport. Measure visible
            // content, not the intentional empty space below the overview.
            const visible = Array.from(node.children)
              .map((child) => child.getBoundingClientRect())
              .filter((rect) => rect.height > 0);
            return (
              Math.max(...visible.map((rect) => rect.bottom)) - node.getBoundingClientRect().top
            );
          }),
        ).toBeLessThan(650);
      const plan = catalog.setup_component_ids.length ? environmentSetupComponents(catalog) : null;
      const ready = plan !== null && plan.every(isEnvironmentComponentReady);
      const primary = page.getByRole('button', {
        name: ready ? '环境已就绪' : '一键部署全部环境',
        exact: true,
      });
      if (
        !catalog.settings.enabled ||
        activeEnvironmentOperation(catalog.active_operation) ||
        !plan ||
        !canSetupEnvironmentPlan(plan)
      ) {
        await expect(primary).toBeDisabled();
      } else {
        await primary.click();
        const dialog = page.getByRole('dialog');
        await expect(dialog.locator('[data-install-component]')).toHaveCount(plan.length);
        for (const component of plan) {
          await expect(
            dialog.locator('[data-install-component="' + component.id + '"]'),
          ).toContainText(component.license);
        }
        await expect(dialog.getByRole('button', { name: '确认下载并安装' })).toBeDisabled();
        await dialog.getByRole('checkbox').check();
        await expect(dialog.getByRole('button', { name: '确认下载并安装' })).toBeEnabled();
        await page.keyboard.press('Escape');
        await expect(dialog).toHaveCount(0);
        await expect(primary).toBeFocused();
      }
      await page.screenshot({
        path: test.info().outputPath('environment-default-' + viewport.width + '.png'),
        fullPage: true,
      });
      await page.getByRole('button', { name: '环境详情', exact: true }).click();
      await page
        .getByRole('dialog', { name: '环境详情', exact: true })
        .getByText('组件详情', { exact: true })
        .click();
      const dialog = page.getByRole('dialog', { name: '环境详情', exact: true });
      for (const component of catalog.components) {
        const row = dialog.locator('[data-component="' + component.id + '"]');
        await expect(row.locator('.badge')).toHaveText(environmentComponentBadge(component).label);
        await expect(row.locator('.component-location')).toHaveText(
          '位置：' + (component.location ?? '未配置'),
        );
      }
      await expect(dialog.getByLabel('集成环境安装目录', { exact: true })).toHaveValue(
        catalog.settings.install_root,
      );
      await expect(dialog.getByLabel('上传文件目录', { exact: true })).toHaveValue(
        catalog.settings.upload_root,
      );
      await expect(dialog.getByLabel('生成结果目录', { exact: true })).toHaveValue(
        catalog.settings.result_root,
      );
      await dialog.getByRole('button', { name: '取消', exact: true }).click();
      await page.reload();
      await expect(page.getByRole('heading', { name: '完整运行环境', exact: true })).toBeVisible();
      await expect(page.getByRole('dialog')).toHaveCount(0);
      await expect(page.locator('.environment-log, .environment-history')).toHaveCount(0);
      expect(writes).toEqual([]);
      expect(errors).toEqual([]);
    },
  );
}
test('owned lightweight inspection persists history and selected operation across reload without model downloads', async ({
  page,
}) => {
  test.skip(
    process.env.PATENTSAR_E2E_ENV_OPERATIONS !== '1',
    'Requires an explicitly owned QA environment state; this performs only installer inspection',
  );
  await page.goto('/#/settings');
  await expect(page.getByRole('heading', { name: '环境管理', exact: true })).toBeVisible();
  const before = await catalogFromServer(page);
  expect(before.settings.enabled).toBe(true);
  expect(before.active_operation).toBeNull();
  const component = before.components.find((item) => item.id === 'installer')!;
  await page.getByRole('button', { name: '环境详情', exact: true }).click();
  await page
    .getByRole('dialog', { name: '环境详情', exact: true })
    .getByText('组件详情', { exact: true })
    .click();
  const response = page.waitForResponse(
    (value) =>
      value.request().method() === 'POST' &&
      value.url().endsWith('/api/v1/environments/operations'),
  );
  await page.getByRole('button', { name: `检测 ${component.name}`, exact: true }).click();
  const created = await response;
  expect(created.status()).toBe(202);
  const request = created.request();
  expect(request.headers()['x-csrf-token']).toBeTruthy();
  const payload = request.postDataJSON() as {
    request_id: string;
    action: string;
    component_ids: string[];
    expected_revision: number;
  };
  expect(payload).toMatchObject({
    action: 'inspect',
    component_ids: ['installer'],
    expected_revision: before.settings.revision,
  });
  expect(payload.request_id).toMatch(/^[A-Za-z0-9_-]{16,64}$/);
  await expect(page).toHaveURL(/#\/settings\?operation=[A-Za-z0-9_-]+/);
  const id = new URLSearchParams(page.url().split('?')[1]).get('operation')!;
  let operation;
  await expect
    .poll(
      async () => {
        const read = await page.request.get(
          `/api/v1/environments/operations/${encodeURIComponent(id)}`,
        );
        expect(read.ok()).toBe(true);
        operation = decodeEnvironmentOperation(await read.json());
        return operation.status;
      },
      { timeout: 60_000, intervals: [300, 500, 1000] },
    )
    .toBe('complete');
  expect(operation!.request_id).toBe(payload.request_id);
  await page.reload();
  await expect(page).toHaveURL(new RegExp(`operation=${id}$`));
  const persisted = await catalogFromServer(page);
  expect(
    persisted.operations.some((item) => item.id === id && item.request_id === payload.request_id),
  ).toBe(true);
  await expect(page.locator('.environment-log, .environment-history')).toHaveCount(0);
});

test('verified existing tool cannot be redundantly installed through the UI', async ({ page }) => {
  test.skip(
    process.env.PATENTSAR_E2E_ENV_INSTALL !== '1',
    'Requires an explicitly owned QA configuration with verified installer; performs no writes',
  );
  await page.goto('/#/settings');
  await expect(page.getByRole('heading', { name: '环境管理', exact: true })).toBeVisible();
  const before = await catalogFromServer(page);
  expect(before.settings.enabled).toBe(true);
  expect(before.active_operation).toBeNull();
  const component = before.components.find((item) => item.id === 'installer')!;
  expect(isEnvironmentComponentReady(component)).toBe(true);
  await page.getByRole('button', { name: '环境详情', exact: true }).click();
  await page
    .getByRole('dialog', { name: '环境详情', exact: true })
    .getByText('组件详情', { exact: true })
    .click();
  const writes: string[] = [];
  page.on('request', (request) => {
    if (request.method() !== 'GET' && request.url().includes('/api/v1/environments'))
      writes.push(request.url());
  });
  const row = page.locator(`[data-component="${component.id}"]`);
  await expect(
    row.getByRole('button', { name: `已安装 ${component.name}`, exact: true }),
  ).toBeDisabled();
  await expect(
    row.getByRole('button', { name: `安装 ${component.name}`, exact: true }),
  ).toHaveCount(0);
  await page.reload();
  const persisted = await catalogFromServer(page);
  expect(persisted.components.find((item) => item.id === component.id)).toEqual(component);
  expect(persisted.operations).toEqual(before.operations);
  expect(writes).toEqual([]);
});
