import { expect, test } from '@playwright/test';
import type { Page } from '@playwright/test';
import { readFile } from 'node:fs/promises';

async function published(page: Page, kind: 'dataset' | 'job') {
  // Observe the actual UI success route, then read its persisted record through
  // the same authenticated controlled browser context. Chromium may discard a
  // POST's CDP body when the hash route changes; never replay a mutation for it.
  await expect(page).toHaveURL(new RegExp(`(?:\\?|&)${kind}=[a-f0-9]{32}`));
  const id = new URLSearchParams(new URL(page.url()).hash.split('?')[1]).get(kind);
  expect(id).toMatch(/^[a-f0-9]{32}$/);
  const response = await page.request.get(
    `/api/v1/sar/${kind === 'dataset' ? 'datasets' : 'jobs'}/${id}`,
  );
  expect(response.status()).toBe(200);
  return response.json();
}

// Owned synthetic state only. These tests prove UI/API/graph execution, not
// OCSR accuracy, article reproduction, clinical benefit or original patent SAR.
for (const width of [390, 800, 1672]) {
  test(`CSV to strict reference results and export at ${width}px`, async ({ page }) => {
    test.skip(process.env.PATENTSAR_E2E_SAR_MUTATIONS !== 'synthetic-isolated-state');
    const errors: string[] = [];
    const forbiddenWrites: string[] = [];
    page.on('pageerror', (error) => errors.push(error.message));
    await page.route('**/api/v1/**', async (route) => {
      const path = new URL(route.request().url()).pathname;
      if (route.request().method() !== 'GET' && !path.startsWith('/api/v1/sar/')) {
        forbiddenWrites.push(path);
        await route.abort();
      } else await route.continue();
    });
    await page.setViewportSize({ width, height: width === 390 ? 844 : 1060 });
    await page.goto('/#/sar');
    await expect(page.getByRole('heading', { name: 'SAR analysis', exact: true })).toBeVisible();
    await expect(
      page.getByRole('combobox', { name: 'Interface language', exact: true }),
    ).toHaveValue('en');
    const importPanel = page.getByRole('region', { name: 'Import data', exact: true });
    await importPanel.getByRole('button', { name: 'CSV file', exact: true }).click();
    const csv = [
      'id,smiles,IC50 (nM),target,assay,cell_line,duration',
      'Example 1,COc1ccc(Cl)cc1,10,T,binding,not applicable,1h',
      'I-255,CCOc1ccc(Cl)cc1,1,T,binding,not applicable,1h',
      '8B,CCOc1ccc(Br)cc1,0.1,T,binding,not applicable,1h',
      'Unresolved,,2,T,binding,not applicable,1h',
    ].join('\n');
    await importPanel.getByLabel('Choose a CSV file', { exact: true }).setInputFiles({
      name: `controlled-SAR-${width}.csv`,
      mimeType: 'text/csv',
      buffer: Buffer.from(csv),
    });
    await importPanel.getByRole('button', { name: 'Preview on server', exact: true }).click();
    await expect(
      importPanel.getByRole('group', { name: 'CSV mapping', exact: true }),
    ).toBeVisible();
    await importPanel
      .getByRole('combobox', { name: 'Source identifier column', exact: true })
      .selectOption('id');
    await importPanel
      .getByRole('combobox', { name: 'SMILES column', exact: true })
      .selectOption('smiles');
    await importPanel.getByRole('checkbox', { name: 'IC50 (nM)', exact: true }).check();
    const saved = page.waitForResponse(
      (response) =>
        response.url().endsWith('/api/v1/sar/datasets/csv') &&
        response.request().method() === 'POST',
    );
    await importPanel.getByRole('button', { name: 'Create CSV dataset', exact: true }).click();
    expect((await saved).status()).toBe(201);
    const dataset = await published(page, 'dataset');
    expect(dataset.row_count).toBe(4);
    expect(dataset.eligible_count).toBe(3);
    await page.getByText('Single-reference comparison (advanced)', { exact: true }).click();
    const rows = page.getByRole('region', { name: 'Choose reference molecule', exact: true });
    await expect(rows.getByRole('rowheader', { name: 'Example 1', exact: true })).toBeVisible();
    await rows
      .getByRole('row', { name: /Example 1/ })
      .getByRole('button', { name: 'Reference', exact: true })
      .click();
    const atom = page.getByRole('button', { name: 'Atom 0 (C)', exact: true });
    await expect(atom).toBeEnabled();
    await atom.click();
    await page.getByRole('button', { name: 'Save region', exact: true }).click();
    await expect(
      page.getByText('Region saved · 1 attachment points', { exact: true }),
    ).toBeVisible();
    await page
      .getByRole('combobox', { name: 'Activity metric', exact: true })
      .selectOption(dataset.metrics[0].id);
    await page
      .getByRole('combobox', { name: 'Activity direction', exact: true })
      .selectOption('lower');
    // Same-document navigation/language changes must not erase the selection.
    await page
      .getByRole('combobox', { name: 'Interface language', exact: true })
      .selectOption('zh-CN');
    await expect(page.getByText('区域已保存 · 1 个连接点', { exact: true })).toBeVisible();
    await page.getByRole('combobox', { name: '界面语言', exact: true }).selectOption('en');
    await expect(
      page.getByRole('combobox', { name: 'Activity direction', exact: true }),
    ).toHaveValue('lower');
    const submitted = page.waitForResponse(
      (response) =>
        /\/api\/v1\/sar\/datasets\/[^/]+\/jobs$/.test(response.url()) &&
        response.request().method() === 'POST',
    );
    await page.getByRole('button', { name: 'Start reference comparison', exact: true }).click();
    expect((await submitted).status()).toBe(202);
    const job = await published(page, 'job');
    const results = page
      .getByRole('region', { name: 'Reference-comparison results', exact: true })
      .first();
    await expect(results.getByText('Complete', { exact: true })).toBeVisible({ timeout: 30000 });
    await page.getByText('Study options', { exact: true }).click();
    await page.getByText('Study task history', { exact: true }).click();
    await expect(
      page
        .getByRole('region', { name: 'SAR jobs', exact: true })
        .getByText('Complete', { exact: true }),
    ).toBeVisible();
    await page.getByText('Study options', { exact: true }).click();
    const valid = results
      .getByRole('row')
      .filter({ has: page.getByRole('rowheader', { name: 'I-255', exact: true }) });
    await expect(valid.getByRole('cell', { name: 'Matched', exact: true })).toBeVisible();
    await expect(valid.getByRole('cell', { name: 'Better', exact: true })).toBeVisible();
    await expect(
      results
        .getByRole('row')
        .filter({ has: page.getByRole('rowheader', { name: '8B', exact: true }) })
        .getByRole('cell', { name: 'Not matched', exact: true }),
    ).toBeVisible();
    await results
      .getByRole('combobox', { name: 'Match filter (current page)', exact: true })
      .selectOption('ineligible');
    await results
      .getByRole('row')
      .filter({ has: page.getByRole('rowheader', { name: 'Unresolved', exact: true }) })
      .getByRole('button', { name: 'Source details', exact: true })
      .click();
    await expect(results.getByText('smiles_missing', { exact: true })).toBeVisible();
    await results
      .getByRole('combobox', { name: 'Match filter (current page)', exact: true })
      .selectOption('');
    const download = page.waitForEvent('download');
    await results.getByRole('button', { name: 'Export all JSON', exact: true }).click();
    const file = await download;
    const exported = JSON.parse(await readFile((await file.path())!, 'utf8'));
    expect(exported.article_reproduction).toBe(false);
    expect(exported.research_only).toBe(true);
    expect(exported.pairs).toHaveLength(3);
    expect(exported.molecules).toHaveLength(4);
    expect(exported.job.id).toBe(job.id);
    expect(exported.region.atom_indices).toEqual([0]);
    expect(
      exported.pairs.find((pair: { label: string }) => pair.label === 'I-255').evidence_basis,
    ).toBe('recorded_context');
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth + 1)).toBe(
      true,
    );
    await page.screenshot({ path: test.info().outputPath(`sar-${width}.png`), fullPage: true });
    await page.reload();
    await expect(results.getByText('Complete', { exact: true })).toBeVisible();
    expect(errors).toEqual([]);
    expect(forbiddenWrites).toEqual([]);
  });
}

test('current extracted task explicitly creates its separate SAR snapshot', async ({ page }) => {
  const project = process.env.PATENTSAR_E2E_SOURCE_PROJECT_ID;
  test.skip(!project || process.env.PATENTSAR_E2E_SAR_MUTATIONS !== 'synthetic-isolated-state');
  await page.goto(`/#/projects/${project}?page=1&tab=original`);
  await page.locator('.topbar').getByRole('button', { name: 'SAR analysis', exact: true }).click();
  await expect(page).toHaveURL(new RegExp(`#/sar\\?project=${project}`));
  await expect(page.getByRole('combobox', { name: 'Source project', exact: true })).toHaveValue(
    project!,
  );
  await expect(page.getByLabel('Dataset title', { exact: true })).toBeHidden();
  await page.getByText('Name (optional)', { exact: true }).click();
  await page.getByLabel('Dataset title', { exact: true }).fill('Controlled extracted snapshot');
  const saved = page.waitForResponse(
    (response) =>
      response.url().endsWith('/api/v1/sar/datasets/project') &&
      response.request().method() === 'POST',
  );
  await page.getByRole('button', { name: 'Continue', exact: true }).click();
  expect((await saved).status()).toBe(201);
  const dataset = await published(page, 'dataset');
  expect(dataset.source_kind).toBe('project');
  expect(dataset.source_project_id).toBe(project);
  expect(dataset.row_count).toBe(30);
  expect(dataset.source_document_sha256).toMatch(/^[a-f0-9]{64}$/);
  await page.locator('.sar-dataset-summary > details > summary').click();
  await expect(
    page.getByRole('heading', { name: 'Controlled extracted snapshot', exact: true }),
  ).toBeVisible();
  await page.getByText('Single-reference comparison (advanced)', { exact: true }).click();
  await expect(
    page.getByRole('button', { name: 'Start reference comparison', exact: true }),
  ).toBeDisabled();
});
