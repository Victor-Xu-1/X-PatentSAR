import { expect, test } from '@playwright/test';
import { job as lifecycleJob } from '../tests/fixtures';

// Explicit isolated saved-observation adapters; not extraction/chemical evidence.
// The browser reads the real installed projection and never submits a model job.
for (const width of [390, 1672]) {
  test(`pending source results remain truthful and localized at ${width}px`, async ({ page }) => {
    const project = process.env.PATENTSAR_E2E_COMPLETION_PENDING_PROJECT;
    expect(project).toBeTruthy();
    const errors: string[] = [],
      writes: string[] = [];
    let published = false;
    const observedJob = {
      ...lifecycleJob,
      id: 'controlled-empty-result-job',
      project_id: project!,
    };
    page.on('pageerror', (error) => errors.push(error.message));
    // Lifecycle/zero-row observations are controlled GET projections only.
    // Published rows still come from the real installed saved-source reader.
    // No worker, scientific task or production state is created or modified.
    await page.route('**/api/v1/**', async (route) => {
      const request = route.request();
      if (request.method() !== 'GET') {
        writes.push(request.url());
        await route.abort();
        return;
      }
      const url = new URL(request.url());
      const current = {
        ...observedJob,
        stages: observedJob.stages.map((stage) =>
          published && stage.name === 'classify' ? { ...stage, count: 1 } : stage,
        ),
      };
      if (url.pathname === '/api/v1/jobs' && url.searchParams.get('project_id') === project) {
        await route.fulfill({ json: { items: [current] } });
      } else if (url.pathname === '/api/v1/jobs/' + observedJob.id) {
        await route.fulfill({ json: current });
      } else if (url.pathname === `/api/v1/projects/${project}/results` && !published) {
        const response = await route.fetch();
        const value = await response.json();
        await route.fulfill({ response, json: { ...value, items: [], total: 0 } });
      } else await route.continue();
    });
    await page.setViewportSize({ width, height: width === 390 ? 844 : 1060 });
    await page.goto('/#/projects/' + project);
    const pending = page.getByText('Results will appear automatically when ready', { exact: true });
    await expect(pending).toBeVisible();
    await expect(pending).toBeInViewport({ ratio: 1 });
    await expect(page.getByRole('button', { name: 'Export results', exact: true })).toBeDisabled();
    await expect(
      page.getByLabel('Select all compounds on this page', { exact: true }),
    ).toBeDisabled();
    const search = page.getByRole('textbox', { name: 'Search results', exact: true });
    await search.fill('no-such-original-id');
    await expect(page.getByText('No matching extraction results', { exact: true })).toBeVisible();
    await search.fill('');
    await expect(pending).toBeVisible();
    await page
      .getByRole('combobox', { name: 'Interface language', exact: true })
      .selectOption('zh-CN');
    await expect(page.getByText('结果就绪后将自动显示', { exact: true })).toBeInViewport({
      ratio: 1,
    });
    await page.reload();
    await expect(page.getByText('结果就绪后将自动显示', { exact: true })).toBeVisible();
    await page.screenshot({ path: test.info().outputPath(`pending-result-${width}.png`) });
    published = true;
    // The existing job observer sees one new stage fact and refreshes results.
    // This does not submit a task or add a second result poller.
    await expect(page.locator('.results-table tbody tr')).toHaveCount(2);
    await expect(page.locator('.frozen-compound').first()).toContainText('Compound 1');
    await expect(page.getByText('结果就绪后将自动显示', { exact: true })).toHaveCount(0);
    await page.screenshot({ path: test.info().outputPath(`published-result-${width}.png`) });
    expect(errors).toEqual([]);
    expect(writes).toEqual([]);
  });

  test(`all-original source projection at ${width}px`, async ({ page }) => {
    const errors: string[] = [],
      writes: string[] = [];
    page.on('pageerror', (error) => errors.push(error.message));
    await page.route('**/api/v1/**', async (route) => {
      if (route.request().method() !== 'GET') {
        writes.push(route.request().url());
        await route.abort();
      } else await route.continue();
    });
    await page.setViewportSize({ width, height: width === 390 ? 844 : 1060 });
    for (const [kind, status] of [
      ['PENDING', 'unavailable'],
      ['COMPLETE', 'valid'],
      ['CONFLICTING', 'invalid'],
      ['HISTORICAL', 'unavailable'],
    ] as const) {
      const project = process.env[`PATENTSAR_E2E_COMPLETION_${kind}_PROJECT`];
      expect(project).toBeTruthy();
      await page.goto('/#/projects/' + project);
      const table = page.locator('.results-table');
      await expect(table.locator('tbody tr')).toHaveCount(2);
      const row = table.locator('tbody tr').first();
      await expect(row.locator('.frozen-compound')).toContainText('Compound 1');
      if (status !== 'valid') await expect(row.locator('.prediction-value')).toHaveCount(0);
      const opener = row.locator('.frozen-compound button');
      await opener.click();
      const dialog = page.getByRole('dialog', {
        name: 'Structure details · Compound 1',
        exact: true,
      });
      await expect(dialog).toBeVisible();
      await expect(
        dialog.getByRole('img', { name: 'Original structure crop for Compound 1', exact: true }),
      ).toBeVisible();
      await dialog
        .getByText('Other original sources for this identifier (1)', { exact: true })
        .click();
      await expect(
        dialog.getByRole('link', { name: 'Original page 1', exact: true }),
      ).toBeVisible();
      if (kind === 'HISTORICAL') {
        await expect(
          dialog.getByText('Historical source references; not validated under current rules.', {
            exact: true,
          }),
        ).toBeVisible();
        await expect(
          dialog.getByText(
            'These repeated sources are confirmed by identifier and spatial evidence, not treated as another unassociated compound.',
            { exact: true },
          ),
        ).toHaveCount(0);
      }
      if (status === 'valid') {
        await dialog.locator('.crop-smiles summary').click();
        await expect(dialog.getByLabel('Current SMILES', { exact: true })).toHaveValue('CCO');
      } else await expect(dialog.getByLabel('Current SMILES', { exact: true })).toHaveCount(0);
      await dialog.getByText('Original extraction evidence / validation', { exact: true }).click();
      await expect(dialog.locator(`.recognition-${status}`)).toBeVisible();
      expect(await dialog.evaluate((el) => el.scrollWidth <= el.clientWidth + 1)).toBe(true);
      await dialog.screenshot({ path: test.info().outputPath(`source-${kind}-${width}.png`) });
      await page.keyboard.press('Escape');
      await expect(opener).toBeFocused();
      await page.reload();
      await expect(table.locator('tbody tr')).toHaveCount(2);
    }
    expect(errors).toEqual([]);
    expect(writes).toEqual([]);
  });
}
