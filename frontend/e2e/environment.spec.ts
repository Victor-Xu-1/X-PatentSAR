import { expect, test } from '@playwright/test';
import type { Page } from '@playwright/test';
import {
  decodeEnvironmentCatalog,
  decodeEnvironmentOperation,
} from '../src/api/environmentDecoders';
import {
  activeEnvironmentOperation,
  environmentStatusLabels,
  selectedEnvironmentComponents,
} from '../src/model/environment';

async function catalogFromServer(page: Page) {
  const response = await page.request.get('/api/v1/environments');
  expect(response.ok(), 'The real authenticated environment catalog must be available').toBe(true);
  return decodeEnvironmentCatalog(await response.json());
}
for (const viewport of [
  { width: 1672, height: 942 },
  { width: 1280, height: 800 },
  { width: 390, height: 844 },
]) {
  test(`real environment catalog, reference layout and confirmation safety at ${viewport.width}×${viewport.height}`, async ({
    page,
  }) => {
    const errors: string[] = [],
      writes: string[] = [];
    page.on('pageerror', (error) => errors.push(error.message));
    page.on('request', (request) => {
      if (request.method() !== 'GET' && request.url().includes('/api/v1/environments'))
        writes.push(request.url());
    });
    await page.setViewportSize(viewport);
    await page.goto('/#/settings');
    await expect(page.getByRole('heading', { name: '环境管理', exact: true })).toBeVisible();
    const catalog = await catalogFromServer(page);
    await expect(page.getByLabel('环境安装目录')).toHaveValue(catalog.settings.install_root);
    for (const component of catalog.components) {
      const row = page.locator(`[data-component="${component.id}"]`);
      await expect(row.getByRole('heading', { name: component.name, exact: true })).toBeVisible();
      await expect(row.locator('.component-title .badge')).toHaveText(
        environmentStatusLabels[component.status],
      );
      await expect(row.locator('.component-metadata')).toContainText(component.version);
      await expect(row.locator('.component-metadata')).toContainText(
        component.detected_version ?? '未报告',
      );
    }
    await expect(page.getByRole('heading', { name: '安装位置', exact: true })).toBeVisible();
    await expect(page.getByRole('heading', { name: '推荐组合', exact: true })).toBeVisible();
    await expect(page.getByRole('heading', { name: '组件库', exact: true })).toBeVisible();
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth + 2)).toBe(
      true,
    );
    await page.getByText('运行诊断', { exact: true }).click();
    await expect(page.getByRole('heading', { name: '产品与存储' })).toBeVisible();
    if (catalog.settings.enabled && !activeEnvironmentOperation(catalog.active_operation)) {
      const component = catalog.components.find((item) => item.installable && item.license.trim());
      expect(
        component,
        'Enabled catalog must expose an approved installable component',
      ).toBeTruthy();
      const opener = page
        .locator(`[data-component="${component!.id}"]`)
        .getByRole('button', { name: `安装 ${component!.name}`, exact: true });
      await opener.click();
      const dialog = page.getByRole('dialog');
      const consent = dialog.getByRole('checkbox');
      await expect(consent).toBeFocused();
      await expect(dialog).toContainText('CPU');
      await expect(dialog).toContainText(component!.license);
      const execution = selectedEnvironmentComponents(catalog.components, [component!.id]);
      await expect(dialog.locator('[data-install-component]')).toHaveCount(execution.length);
      for (const item of execution) {
        const entry = dialog.locator(`[data-install-component="${item.id}"]`);
        await expect(entry).toContainText(item.name);
        await expect(entry).toContainText(item.version);
        await expect(entry).toContainText(item.license);
      }
      await expect(dialog.getByRole('button', { name: '确认下载并安装' })).toBeDisabled();
      await consent.check();
      const confirm = dialog.getByRole('button', { name: '确认下载并安装' });
      await expect(confirm).toBeEnabled();
      await confirm.focus();
      await page.keyboard.press('Tab');
      await page.keyboard.press('Tab');
      expect(await dialog.evaluate((element) => element.contains(document.activeElement))).toBe(
        true,
      );
      const bounds = await dialog.boundingBox();
      expect(bounds!.x).toBeGreaterThanOrEqual(0);
      expect(bounds!.x + bounds!.width).toBeLessThanOrEqual(viewport.width);
      await page.keyboard.press('Escape');
      await expect(dialog).toHaveCount(0);
      await expect(opener).toBeFocused();
    } else {
      await expect(page.getByRole('button', { name: '检测缺失组件' })).toBeDisabled();
    }
    if (viewport.width < 760) {
      const menu = page.getByLabel('展开或收起导航');
      await menu.click();
      await expect(menu).toHaveAttribute('aria-expanded', 'true');
      expect(await menu.evaluate((element) => element.closest('[inert]'))).toBeNull();
      const bounds = await menu.boundingBox();
      expect(bounds!.width).toBeGreaterThanOrEqual(44);
      expect(bounds!.height).toBeGreaterThanOrEqual(44);
      expect(
        await menu.evaluate((element) => {
          const box = element.getBoundingClientRect();
          return element.contains(
            document.elementFromPoint(box.x + box.width / 2, box.y + box.height / 2),
          );
        }),
      ).toBe(true);
      const sidebar = await page.locator('.sidebar').boundingBox();
      const header = await page.locator('.topbar').boundingBox();
      expect(sidebar!.y).toBeGreaterThanOrEqual(header!.y + header!.height);
      await expect.poll(async () => (await page.locator('.sidebar').boundingBox())!.x).toBe(0);
      await page.screenshot({ path: test.info().outputPath('environment-mobile-navigation.png') });
    }
    await expect(page.getByRole('button', { name: '环境管理', exact: true })).toHaveAttribute(
      'aria-current',
      'page',
    );
    await expect(page.getByRole('button', { name: '运行环境', exact: true })).toHaveCount(0);
    if (viewport.width < 760) {
      const menu = page.getByLabel('展开或收起导航');
      await menu.click();
      await expect(menu).toHaveAttribute('aria-expanded', 'false');
      await expect(menu).toBeFocused();
      await expect
        .poll(async () => {
          const drawer = await page.locator('.sidebar').boundingBox();
          return drawer!.x + drawer!.width;
        })
        .toBeLessThanOrEqual(0);
      await expect(page.locator('main')).not.toHaveAttribute('inert');
      await page.keyboard.press('Enter');
      await expect(menu).toHaveAttribute('aria-expanded', 'true');
      await page.keyboard.press('Escape');
      await expect(menu).toHaveAttribute('aria-expanded', 'false');
      await expect(menu).toBeFocused();
    }
    await page.screenshot({
      path: test.info().outputPath(`environment-${viewport.width}.png`),
      fullPage: true,
    });
    await page.reload();
    await expect(page.getByLabel('环境安装目录')).toHaveValue(catalog.settings.install_root);
    await expect(page.locator('.environment-footer')).toContainText('X-PatentSAR');
    expect(
      writes,
      'Reading, opening/closing confirmation and reloading must never install',
    ).toEqual([]);
    expect(errors).toEqual([]);
  });
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
  await expect(page.getByLabel('环境后台操作')).toContainText(id);
  const persisted = await catalogFromServer(page);
  expect(
    persisted.operations.some((item) => item.id === id && item.request_id === payload.request_id),
  ).toBe(true);
  const log = page.getByLabel('环境操作日志');
  await expect(log).toHaveValue(
    operation!.log_tail.slice(-200).join('\n') || '服务端尚未提供日志。',
  );
});
