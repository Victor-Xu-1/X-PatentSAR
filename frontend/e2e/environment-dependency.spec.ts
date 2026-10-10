import { expect, test } from '@playwright/test';
import { decodeEnvironmentCatalog } from '../src/api/environmentDecoders';
import { environmentBytes, selectedEnvironmentComponents } from '../src/model/environment';
import {
  canInstallEnvironmentPlan,
  environmentComponentAction,
} from '../src/model/environmentStatus';

for (const viewport of [
  { width: 1672, height: 942 },
  { width: 1280, height: 800 },
  { width: 390, height: 844 },
]) {
  test(`real dependency plans preserve install consent or inspection-first state at ${viewport.width}×${viewport.height}`, async ({
    page,
  }) => {
    const writes: string[] = [];
    await page.setViewportSize(viewport);
    page.on('request', (request) => {
      if (request.method() !== 'GET' && request.url().includes('/api/v1/environments'))
        writes.push(request.url());
    });
    await page.goto('/#/settings');
    await expect(page.getByRole('heading', { name: '环境管理', exact: true })).toBeVisible();
    const response = await page.request.get('/api/v1/environments');
    expect(response.ok()).toBe(true);
    const catalog = decodeEnvironmentCatalog(await response.json());
    expect(catalog.settings.enabled).toBe(true);
    expect(
      catalog.active_operation,
      'This read-only confirmation check requires idle owned QA state',
    ).toBeNull();
    for (const id of ['base', 'admet-models'] as const) {
      if ((await page.getByRole('dialog', { name: '环境详情', exact: true }).count()) === 0) {
        await page.getByRole('button', { name: '环境详情', exact: true }).click();
        await page
          .getByRole('dialog', { name: '环境详情', exact: true })
          .getByText('组件详情', { exact: true })
          .click();
      }
      const execution = selectedEnvironmentComponents(catalog.components, [id]);
      expect(execution.length).toBeGreaterThan(1);
      const selected = catalog.components.find((item) => item.id === id)!;
      const action = environmentComponentAction(selected);
      if (!canInstallEnvironmentPlan(execution)) {
        const label = { installed: '已安装', inspect: '先检测', install: '安装', repair: '修复' }[
          action
        ];
        const button = page
          .locator(`[data-component="${id}"]`)
          .getByRole('button', { name: `${label} ${selected.name}`, exact: true });
        if (action === 'installed' || action === 'inspect') await expect(button).toBeDisabled();
        await expect(page.getByRole('dialog', { name: '确认环境安装', exact: true })).toHaveCount(
          0,
        );
        continue;
      }
      const label = action === 'repair' ? '修复' : '安装';
      const opener = page
        .locator(`[data-component="${id}"]`)
        .getByRole('button', { name: `${label} ${selected.name}`, exact: true });
      await opener.click();
      const dialog = page.getByRole('dialog');
      const box = await dialog.boundingBox();
      expect(box!.x).toBeGreaterThanOrEqual(0);
      expect(box!.x + box!.width).toBeLessThanOrEqual(viewport.width);
      expect(box!.y).toBeGreaterThanOrEqual(0);
      expect(box!.y + box!.height).toBeLessThanOrEqual(viewport.height);
      expect(
        await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth + 2),
      ).toBe(true);
      expect(
        await dialog
          .locator('[data-install-component]')
          .evaluateAll((elements) =>
            elements.map((element) => element.getAttribute('data-install-component')),
          ),
      ).toEqual(execution.map((item) => item.id));
      for (const item of execution) {
        const row = dialog.locator(`[data-install-component="${item.id}"]`);
        await expect(row).toContainText(item.name);
        await expect(row).toContainText(item.version);
        await expect(row).toContainText(environmentBytes(item.download_bytes));
        await expect(row).toContainText(item.license);
        await expect(row).toContainText(item.id === id ? '所选组件' : '前置依赖');
      }
      if (id === 'admet-models')
        await expect(dialog.locator('[data-install-component="admet"]')).toHaveCount(1);
      const consent = dialog.getByRole('checkbox');
      await expect(consent).not.toBeChecked();
      await expect(dialog.getByRole('button', { name: '确认下载并安装' })).toBeDisabled();
      await page.screenshot({ path: test.info().outputPath(`prerequisites-${id}.png`) });
      await consent.check();
      await expect(dialog.getByRole('button', { name: '确认下载并安装' })).toBeEnabled();
      await page.keyboard.press('Escape');
      await expect(dialog).toHaveCount(0);
      await expect(page.getByRole('button', { name: '环境详情', exact: true })).toBeVisible();
    }
    expect(
      writes,
      'No install, inspection, cancellation or settings write is authorized by this test',
    ).toEqual([]);
  });
}
