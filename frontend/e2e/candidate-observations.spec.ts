import { expect, test } from '@playwright/test';
import { decodeResults } from '../src/api/decoders';

// Real coordinator/worker/source reader with explicit synthetic model outputs.
// This is UI/protocol evidence, not real-patent or OCSR chemical acceptance.
for (const width of [390, 1672]) {
  test(`observed candidates stay unassigned in both languages at ${width}px`, async ({ page }) => {
    const project = process.env.PATENTSAR_E2E_CANDIDATE_PROJECT_ID;
    expect(project, 'Requires the isolated native candidate-observation fixture').toBeTruthy();
    const writes: string[] = [],
      errors: string[] = [];
    page.on('pageerror', (error) => errors.push(error.message));
    await page.route('**/api/v1/**', async (route) => {
      if (route.request().method() !== 'GET') {
        writes.push(route.request().url());
        await route.abort();
      } else await route.continue();
    });
    await page.setViewportSize({ width, height: width === 390 ? 844 : 1060 });
    await page.goto('/#/projects/' + project);
    const rows = page.locator('.results-table tbody tr[data-compound]');
    // Wait for the normal UI session and source read, not a fixed delay or an
    // unauthenticated API request racing initial navigation.
    await expect(rows).toHaveCount(2);
    const endpoint = `/api/v1/projects/${project}/results`;
    const response = await page.request.get(endpoint);
    expect(response.ok(), await response.text()).toBeTruthy();
    const before = decodeResults(await response.json());
    expect(before.total).toBe(2);
    for (const row of before.items) {
      expect(row.identifier_label ?? null).toBeNull();
      expect(row.smiles).toBeNull();
      expect(row.activities).toEqual([]);
      expect(row.recognition?.status).toBe('unavailable');
      expect(row.recognition?.quality_flag).toBe('unassigned_source_identity');
      expect(row.admet?.properties ?? []).toEqual([]);
    }
    const opener = rows.first().locator('.frozen-compound button');
    await opener.click();
    const dialog = page.getByRole('dialog');
    await expect(dialog).toBeVisible();
    await expect(dialog).toHaveAccessibleName(/^Structure details/);
    await expect(dialog.locator('.crop-comparison figure')).toHaveCount(1);
    await expect(dialog.locator('.prediction-evidence')).toHaveCount(0);
    await expect(dialog.getByRole('status')).toHaveText(
      'Candidate identifier unconfirmed; redraw withheld',
    );
    await expect(dialog.locator('img')).toHaveCount(1);
    await expect
      .poll(() =>
        dialog.locator('img').evaluate((image) => (image as HTMLImageElement).naturalWidth),
      )
      .toBeGreaterThan(0);
    await dialog
      .locator('details')
      .filter({ has: page.locator('.recognition-details') })
      .locator('summary')
      .click();
    await expect(dialog.getByText('Observed · unassigned', { exact: true })).toBeVisible();
    await expect(dialog.getByLabel('Current SMILES', { exact: true })).toHaveCount(0);
    await page
      .getByRole('combobox', { name: 'Interface language', exact: true })
      .selectOption('zh-CN');
    await expect(dialog).toHaveAccessibleName(/^结构详情/);
    await expect(dialog.getByText('已观察 · 编号待确认', { exact: true })).toBeVisible();
    await expect(dialog.getByText(/原图已保留，原文编号待核验。/)).toBeVisible();
    await expect(dialog.getByLabel('当前 SMILES', { exact: true })).toHaveCount(0);
    await dialog.screenshot({ path: test.info().outputPath(`candidate-zh-${width}.png`) });
    await page.getByRole('combobox', { name: '界面语言', exact: true }).selectOption('en');
    await expect(dialog.getByText('Observed · unassigned', { exact: true })).toBeVisible();
    expect(await dialog.evaluate((element) => element.scrollWidth <= element.clientWidth + 1)).toBe(
      true,
    );
    await dialog.screenshot({ path: test.info().outputPath(`candidate-en-${width}.png`) });
    await page.keyboard.press('Escape');
    await expect(opener).toBeFocused();
    const after = decodeResults(await (await page.request.get(endpoint)).json());
    expect(after.items).toEqual(before.items);
    expect(writes).toEqual([]);
    expect(errors).toEqual([]);
  });
}
