import { expect, test } from '@playwright/test';
import { createNetwork } from './sar-network-actions';

// Controlled native SAR input, submitted only through the isolated fixture UI.
// No interception supplies molecules, source coordinates, rows or success.
for (const width of [1672, 390]) {
  test(`original atom pointers and explicit region choices at ${width}px`, async ({
    page,
  }, info) => {
    test.skip(process.env.PATENTSAR_E2E_SAR_MUTATIONS !== 'synthetic-isolated-state');
    await page.setViewportSize({ width, height: width === 390 ? 844 : 1060 });
    await page.emulateMedia({ reducedMotion: 'reduce' });
    const errors: string[] = [],
      writes: string[] = [];
    page.on('pageerror', (error) => errors.push(error.message));
    page.on('request', (request) => {
      if (request.method() !== 'GET' && new URL(request.url()).pathname.startsWith('/api/v1/'))
        writes.push(new URL(request.url()).pathname);
    });
    const { job, report } = await createNetwork(page, width, undefined, true, true, {
      overlappingRegion: true,
    });
    const before = await (
      await page.request.get(`/api/v1/sar/jobs/${job}/study/export?format=json`)
    ).body();
    const published = JSON.parse(before.toString());
    await report.getByRole('button', { name: 'Variable regions', exact: true }).click();
    const network = report.getByRole('region', { name: 'Single-site comparisons', exact: true });
    const map = network.locator('.sar-reference-map-image');
    await expect(map.locator('img')).toBeVisible();
    const targets = map.locator('.sar-region-hotspots > button');
    await expect(targets.first()).toBeVisible();
    const displayed = await targets.evaluateAll((buttons) =>
      buttons.flatMap((button) => JSON.parse(button.getAttribute('data-region-ids')!) as string[]),
    );
    expect(new Set(displayed)).toEqual(
      new Set(published.report.regions.map((item: { region: { id: string } }) => item.region.id)),
    );
    expect(
      await targets.evaluateAll(
        (buttons) => new Set(buttons.map((button) => button.getAttribute('data-atom-index'))).size,
      ),
    ).toBe(await targets.count());
    const activeWrites = writes.length;
    // Locate from the original index, then perform a real pointer input.
    const atom = map.locator('.sar-region-hotspots > button[data-atom-index="0"]');
    await atom.scrollIntoViewIfNeeded();
    const bounds = await atom.boundingBox();
    expect(bounds).not.toBeNull();
    await page.mouse.click(bounds!.x + bounds!.width / 2, bounds!.y + bounds!.height / 2);
    let chooser = page.getByRole('dialog', { name: 'Variable regions · Atom 0 (C)', exact: true });
    await expect(chooser.getByRole('button', { name: 'Linker 原文', exact: true })).toBeVisible();
    await expect(
      chooser.getByRole('button', { name: 'Expanded Linker 原文', exact: true }),
    ).toBeVisible();
    expect(
      await chooser.evaluate((node) => {
        const rect = node.getBoundingClientRect();
        return (
          rect.left >= 0 && rect.right <= innerWidth && rect.top >= 0 && rect.bottom <= innerHeight
        );
      }),
    ).toBe(true);
    await page.screenshot({
      path: info.outputPath('atom-region-choice.png'),
      animations: 'disabled',
    });
    await chooser.press('Escape');
    await expect(chooser).not.toBeVisible();
    await expect(atom).toBeFocused();
    await atom.click();
    chooser = page.getByRole('dialog', { name: 'Variable regions · Atom 0 (C)', exact: true });
    await chooser.getByRole('button', { name: 'Expanded Linker 原文', exact: true }).click();
    await expect(
      network
        .locator('.sar-region-legend')
        .getByRole('button', { name: 'Expanded Linker 原文', exact: true }),
    ).toHaveAttribute('aria-pressed', 'true');
    await expect(network.getByRole('button', { name: 'Compare 2', exact: true })).toBeVisible();
    await page
      .getByRole('combobox', { name: 'Interface language', exact: true })
      .selectOption('zh-CN');
    const localizedAtom = page
      .getByRole('region', { name: '研究报告', exact: true })
      .getByRole('region', { name: '单点结构对比', exact: true })
      .locator('.sar-region-hotspots > button[data-atom-index="0"]');
    await localizedAtom.click();
    chooser = page.getByRole('dialog', { name: '变化区域 · 原子 0（C）', exact: true });
    await expect(
      chooser.getByRole('button', { name: 'Expanded Linker 原文', exact: true }),
    ).toBeVisible();
    await chooser.press('Escape');
    const after = await (
      await page.request.get(`/api/v1/sar/jobs/${job}/study/export?format=json`)
    ).body();
    expect(before.equals(after)).toBe(true);
    expect(writes.slice(activeWrites)).toEqual([]);
    expect(errors).toEqual([]);
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth + 1)).toBe(
      true,
    );
  });
}
