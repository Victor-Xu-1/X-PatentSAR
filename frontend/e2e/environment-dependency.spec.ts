import { expect, test } from '@playwright/test';
import { decodeEnvironmentCatalog } from '../src/api/environmentDecoders';
import { environmentBytes, selectedEnvironmentComponents } from '../src/model/environment';

for (const viewport of [
  { width: 1672, height: 942 },
  { width: 1280, height: 800 },
  { width: 390, height: 844 },
]) {
  test(`real base and ADMET model consent includes every server prerequisite without starting installation at ${viewport.width}×${viewport.height}`, async ({
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
      const execution = selectedEnvironmentComponents(catalog.components, [id]);
      expect(execution.length).toBeGreaterThan(1);
      const selected = catalog.components.find((item) => item.id === id)!;
      const opener = page
        .locator(`[data-component="${id}"]`)
        .getByRole('button', { name: `安装 ${selected.name}`, exact: true });
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
      await expect(opener).toBeFocused();
    }
    expect(
      writes,
      'No install, inspection, cancellation or settings write is authorized by this test',
    ).toEqual([]);
  });
}
