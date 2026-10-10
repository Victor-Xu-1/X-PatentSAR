import { expect, test, type Locator } from '@playwright/test';
import { syntheticSnapshot } from './sarSnapshotFixture';
import { cardProtocol } from './sarCardProtocolFixture';

async function compactMark(mark: Locator) {
  await expect(mark).toHaveText('LeadG1');
  await expect(mark).toHaveAttribute('title', 'Selected candidate · Priority group 1');
  expect(await mark.evaluate((element) => getComputedStyle(element).whiteSpace)).toBe('nowrap');
  expect(
    await mark.evaluate((element) => {
      const box = element.getBoundingClientRect();
      const cell = element.closest('td')!.getBoundingClientRect();
      return box.width <= cell.width && box.height < 40;
    }),
  ).toBe(true);
}

for (const width of [390, 800, 1672]) {
  test(`candidate sources require current reads at ${width}px`, async ({ page }, info) => {
    test.skip(process.env.PATENTSAR_E2E_SAR_MUTATIONS !== 'synthetic-isolated-state');
    const errors: string[] = [],
      writes: string[] = [];
    page.on('pageerror', (error) => errors.push(error.message));
    await page.route('**/api/v1/**', (route) => {
      if (route.request().method() === 'GET') return route.continue();
      writes.push(new URL(route.request().url()).pathname);
      return route.abort();
    });
    await page.setViewportSize({ width, height: width === 390 ? 844 : 1060 });
    await page.emulateMedia({ reducedMotion: 'reduce' });
    const dataset = await syntheticSnapshot(page);
    const fixture = await cardProtocol(page, dataset);
    const original = JSON.stringify(fixture.report);
    await page.getByRole('region', { name: 'Study report', exact: true }).waitFor();
    const report = page.locator('section.sar-study');
    await report.getByRole('button', { name: 'Activity table', exact: true }).click();
    const panel = report.locator('.sar-study-report > section').nth(5);
    await panel.getByRole('rowheader').waitFor();
    await panel.getByRole('button', { name: 'Column settings', exact: true }).click();
    const chooser = page.getByRole('dialog', { name: 'Column settings', exact: true });
    await chooser
      .getByRole('checkbox', { name: 'Show column Source details', exact: true })
      .check();
    await chooser.getByRole('button', { name: 'Close dialog', exact: true }).first().click();
    const row = panel.locator('tbody tr').first();
    const mark = row.locator('.sar-lead-mark');
    const identifier = row.locator('th button');
    const sourceButton = row.getByRole('button', { name: 'Source details', exact: true });
    await compactMark(mark);
    await mark.click();
    const source = page.getByRole('dialog', {
      name: 'Source details · ' + fixture.molecule.label,
      exact: true,
    });
    await source.getByText('Original records', { exact: true }).waitFor();
    const rawValues = await source.locator('.sar-facts').first().innerText();
    await source.getByRole('button', { name: 'Close dialog', exact: true }).first().click();
    await expect(mark).toBeFocused();
    await page.screenshot({
      path: info.outputPath('candidate-active.png'),
      animations: 'disabled',
    });
    await page
      .getByRole('combobox', { name: 'Interface language', exact: true })
      .selectOption('zh-CN');
    await expect(mark).toHaveText('LeadG1');
    await expect(mark).toHaveAttribute('title', '研究已选候选 · 优先组 1');
    await expect(mark).toHaveAccessibleName(
      '来源详情 · ' + fixture.molecule.label + ' · 研究已选候选 · 优先组 1',
    );
    await mark.click();
    const translated = page.getByRole('dialog', {
      name: '来源详情 · ' + fixture.molecule.label,
      exact: true,
    });
    await translated.getByText('原始记录', { exact: true }).waitFor();
    expect(await translated.locator('.sar-facts').first().innerText()).toBe(rawValues);
    await translated.getByRole('button', { name: '关闭对话框', exact: true }).first().click();
    await expect(mark).toBeFocused();
    await page.getByRole('combobox', { name: '界面语言', exact: true }).selectOption('en');

    let failedReads = 0;
    let rejectRows = true;
    await page.route(`**/api/v1/sar/jobs/${fixture.job.id}/study/rows?*`, (route) => {
      if (!rejectRows) return route.fallback();
      failedReads++;
      return route.fulfill({
        status: 503,
        json: {
          error: {
            code: 'sar_controlled_read_failure',
            message: 'Controlled browser read failure',
          },
        },
      });
    });
    await report.getByRole('button', { name: 'Overview', exact: true }).click();
    await report.getByRole('button', { name: 'Activity table', exact: true }).click();
    await panel.getByRole('alert').waitFor();
    expect(failedReads).toBe(2);
    await expect(identifier).toBeDisabled();
    await expect(mark).toBeDisabled();
    await expect(sourceButton).toBeDisabled();
    await expect(page.getByRole('dialog')).toHaveCount(0);
    await mark.scrollIntoViewIfNeeded();
    await page.screenshot({
      path: info.outputPath('candidate-read-failure.png'),
      animations: 'disabled',
    });
    rejectRows = false;
    await panel.getByRole('button', { name: 'Reload', exact: true }).click();
    await expect(identifier).toBeEnabled();
    await expect(mark).toBeEnabled();
    await expect(sourceButton).toBeEnabled();
    await sourceButton.click();
    await source.getByText('Original records', { exact: true }).waitFor();
    expect(await source.locator('.sar-facts').first().innerText()).toBe(rawValues);
    await source.getByRole('button', { name: 'Close dialog', exact: true }).first().click();
    await expect(sourceButton).toBeFocused();

    await report.getByRole('button', { name: 'Leads', exact: true }).click();
    const card = report
      .getByRole('region', { name: 'Leads', exact: true })
      .locator('.sar-lead-card')
      .first();
    const cardSource = card.getByRole('button', { name: 'Source details', exact: true });
    await expect(cardSource).toBeEnabled();
    const jobPath = `**/api/v1/sar/jobs/${fixture.job.id}`;
    await page.route(jobPath, (route) =>
      route.fulfill({
        status: 503,
        json: {
          error: { code: 'sar_controlled_read_failure', message: 'Controlled report read failure' },
        },
      }),
    );
    await report.getByRole('button', { name: 'Refresh', exact: true }).click();
    await report.getByRole('alert').first().waitFor();
    await expect(cardSource).toBeDisabled();
    await expect(page.getByRole('dialog')).toHaveCount(0);
    await card.screenshot({
      path: info.outputPath('candidate-card-read-failure.png'),
      animations: 'disabled',
    });
    await page.unroute(jobPath);
    await report.getByRole('button', { name: 'Refresh', exact: true }).click();
    await expect(cardSource).toBeEnabled();
    const jobs = await page.request.get(`/api/v1/sar/datasets/${dataset.id}/jobs`);
    expect((await jobs.json()).items).toEqual([]);
    expect(JSON.stringify(fixture.report)).toBe(original);
    expect(errors).toEqual([]);
    expect(writes).toEqual([]);
  });
}
