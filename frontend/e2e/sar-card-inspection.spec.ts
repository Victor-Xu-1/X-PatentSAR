import { expect, test, type Locator } from '@playwright/test';
import { syntheticSnapshot } from './sarSnapshotFixture';
import { cardProtocol } from './sarCardProtocolFixture';

async function paintedSize(image: Locator) {
  return image.evaluate((node) => {
    const picture = node as HTMLImageElement;
    const box = picture.getBoundingClientRect();
    const scale = Math.min(box.width / picture.naturalWidth, box.height / picture.naturalHeight);
    const style = getComputedStyle(picture);
    const canvas = picture.parentElement!;
    return {
      width: picture.naturalWidth * scale,
      height: picture.naturalHeight * scale,
      box: box.toJSON(),
      naturalWidth: picture.naturalWidth,
      naturalHeight: picture.naturalHeight,
      maxHeight: style.maxHeight,
      maxWidth: style.maxWidth,
      canvas: canvas.getBoundingClientRect().toJSON(),
      canvasInline: canvas.getAttribute('style'),
    };
  });
}

// Read-only card interactions on an isolated layout-only report DTO. Actual
// backend drawings are reused; no extraction/analysis/model task is started.
for (const width of [390, 800, 1672]) {
  test(`result cards share safe inspection at ${width}px`, async ({ page }, info) => {
    test.skip(process.env.PATENTSAR_E2E_SAR_MUTATIONS !== 'synthetic-isolated-state');
    const errors: string[] = [],
      writes: string[] = [];
    page.on('pageerror', (error) => errors.push(error.message));
    await page.route('**/api/v1/**', async (route) => {
      if (route.request().method() !== 'GET') {
        writes.push(new URL(route.request().url()).pathname);
        await route.abort();
      } else await route.continue();
    });
    await page.setViewportSize({ width, height: width === 390 ? 844 : 1060 });
    await page.emulateMedia({ reducedMotion: 'reduce' });
    const dataset = await syntheticSnapshot(page);
    const fixture = await cardProtocol(page, dataset);
    const original = JSON.stringify(fixture.report);
    for (const sample of [
      {
        tab: 'Leads',
        translatedTab: '研究先导候选',
        label: fixture.molecule.label,
        translated: fixture.molecule.label,
      },
      { tab: 'Scaffolds', translatedTab: '研究骨架', label: 'Core 1', translated: '母核 1' },
      {
        tab: 'Fragment summary',
        translatedTab: '片段汇总',
        label: 'Fragment 1',
        translated: '片段 1',
      },
    ]) {
      const report = page.getByRole('region', { name: 'Study report', exact: true });
      await report.getByRole('button', { name: sample.tab, exact: true }).click();
      const view = report.getByRole('region', { name: sample.tab, exact: true });
      const opener = view.getByRole('button', {
        name: 'Enlarge structure ' + sample.label,
        exact: true,
      });
      await expect(opener).toBeEnabled();
      const image = opener.locator('img');
      const source = await image.getAttribute('src');
      const reads = fixture.drawings.length;
      await opener.click();
      const dialog = page.getByRole('dialog', {
        name: 'Molecular preview · ' + sample.label,
        exact: true,
      });
      const enlarged = dialog.getByRole('img', { name: sample.label, exact: true });
      await expect(enlarged).toHaveAttribute('src', source!);
      const fitSize = await paintedSize(enlarged);
      const pane = dialog.getByRole('region', { name: 'Molecular canvas', exact: true });
      expect(
        await pane.evaluate((element) => {
          const bounds = element.getBoundingClientRect();
          const image = element.querySelector('img')!.getBoundingClientRect();
          return (
            image.left >= bounds.left - 1 &&
            image.top >= bounds.top - 1 &&
            image.right <= bounds.right + 1 &&
            image.bottom <= bounds.bottom + 1
          );
        }),
      ).toBe(true);
      await page.screenshot({
        path: info.outputPath(sample.tab + '-fit.png'),
        animations: 'disabled',
      });
      for (let i = 0; i < 12; i++)
        await dialog.getByRole('button', { name: 'Zoom in structure', exact: true }).click();
      await expect(dialog.getByLabel('Magnification relative to fit', { exact: true })).toHaveText(
        '400%',
      );
      const magnifiedSize = await paintedSize(enlarged);
      console.log(
        'card_magnification_geometry',
        JSON.stringify({ tab: sample.tab, width, fitSize, magnifiedSize }),
      );
      expect(magnifiedSize.width / fitSize.width).toBeCloseTo(4, 1);
      expect(magnifiedSize.height / fitSize.height).toBeCloseTo(4, 1);
      expect(
        await pane.evaluate(
          (element) =>
            element.scrollWidth > element.clientWidth &&
            element.scrollHeight > element.clientHeight,
        ),
      ).toBe(true);
      await pane.evaluate((element) => element.scrollTo({ left: 0, top: 0, behavior: 'instant' }));
      await pane.focus();
      await page.keyboard.press('ArrowRight');
      await expect.poll(() => pane.evaluate((element) => element.scrollLeft)).toBeGreaterThan(0);
      await dialog.getByRole('button', { name: 'Fit', exact: true }).click();
      await page.keyboard.press('Escape');
      await expect(page.getByRole('dialog')).toHaveCount(0);
      await expect(opener).toBeFocused();
      await page
        .getByRole('combobox', { name: 'Interface language', exact: true })
        .selectOption('zh-CN');
      const localizedView = page.getByRole('region', { name: sample.translatedTab, exact: true });
      const localizedOpener = localizedView.getByRole('button', {
        name: '放大结构 ' + sample.translated,
        exact: true,
      });
      await localizedOpener.click();
      const translated = page.getByRole('dialog', {
        name: '结构预览 · ' + sample.translated,
        exact: true,
      });
      await expect(
        translated.getByRole('img', { name: sample.translated, exact: true }),
      ).toHaveAttribute('src', source!);
      expect(fixture.drawings.length).toBe(reads);
      await page.keyboard.press('Escape');
      await expect(page.getByRole('dialog')).toHaveCount(0);
      await expect(localizedOpener).toBeFocused();
      await page.getByRole('combobox', { name: '界面语言', exact: true }).selectOption('en');
    }
    const jobs = await page.request.get(`/api/v1/sar/datasets/${dataset.id}/jobs`);
    expect((await jobs.json()).items).toEqual([]);
    expect(JSON.stringify(fixture.report)).toBe(original);
    expect(errors).toEqual([]);
    expect(writes).toEqual([]);
  });
}
