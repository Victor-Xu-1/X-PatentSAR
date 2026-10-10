import { expect, test, type Locator } from '@playwright/test';
import { syntheticSnapshot } from './sarSnapshotFixture';

async function expectCompleteBadge(atom: Locator, index: number) {
  const badge = atom.locator('span');
  await expect(badge).toHaveText(String(index));
  expect(
    await badge.evaluate((span) => {
      const text = document.createRange();
      text.selectNodeContents(span);
      return text.getClientRects().length;
    }),
  ).toBe(1);
  expect(await badge.evaluate((span) => getComputedStyle(span).opacity)).toBe('1');
}

// Exact RDKit atom identities from isolated authored graphs, not OCSR evidence.
// Only snapshot preparation writes; selection and localization stay unsaved.
for (const width of [390, 800, 1672]) {
  for (const sample of [
    { label: 'Compound 29', index: 15 },
    { label: 'Compound 30', index: 115 },
  ]) {
    test(`atom ${sample.index} remains one label at ${width}px`, async ({ page }, info) => {
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
      await page.getByText('Single-reference comparison (advanced)', { exact: true }).click();
      const browser = page.getByRole('region', { name: 'Choose reference molecule', exact: true });
      const row = browser.getByRole('row').filter({
        has: page.getByRole('rowheader', { name: sample.label, exact: true }),
      });
      await expect(row.getByRole('button', { name: 'Reference', exact: true })).toBeEnabled();
      await row.getByRole('button', { name: 'Reference', exact: true }).click();
      const panel = page.getByRole('region', { name: 'Select variable region', exact: true });
      const atom = panel.locator('.sar-atom').filter({ hasText: new RegExp(`^${sample.index}$`) });
      await expect(atom).toBeEnabled();
      await atom.focus();
      await atom.press('Space');
      await expect(atom).toHaveAttribute('aria-pressed', 'true');
      await expect(atom).toHaveAttribute('aria-label', `Atom ${sample.index} (C)`);
      await expect(panel.locator('output').first()).toHaveText(`Selected atoms: ${sample.index}`);
      await expectCompleteBadge(atom, sample.index);
      await page
        .getByRole('combobox', { name: 'Interface language', exact: true })
        .selectOption('zh-CN');
      const localizedPanel = page.getByRole('region', { name: '选择变化区域', exact: true });
      const localizedAtom = localizedPanel
        .locator('.sar-atom')
        .filter({ hasText: new RegExp(`^${sample.index}$`) });
      await expect(localizedPanel.getByRole('heading')).toHaveText(
        `选择变化区域 · ${sample.label}`,
      );
      await expect(localizedAtom).toHaveAttribute('aria-label', `原子 ${sample.index}（C）`);
      await expect(localizedAtom).toHaveAttribute('aria-pressed', 'true');
      await expectCompleteBadge(localizedAtom, sample.index);
      expect(
        await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth + 1),
      ).toBe(true);
      await page.screenshot({
        path: info.outputPath('selected-index.png'),
        animations: 'disabled',
      });
      const jobs = await page.request.get(`/api/v1/sar/datasets/${dataset.id}/jobs`);
      expect(jobs.ok()).toBe(true);
      expect((await jobs.json()).items).toEqual([]);
      expect(writes).toEqual([]);
      expect(errors).toEqual([]);
    });
  }
}
