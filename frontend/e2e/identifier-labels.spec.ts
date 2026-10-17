import { expect, test } from '@playwright/test';
import { LOCALE_STORAGE_KEY } from '../src/i18n/locale';

test.beforeEach(async ({ page }) => {
  await page.addInitScript((key) => {
    if (localStorage.getItem(key) === null) localStorage.setItem(key, 'zh-CN');
  }, LOCALE_STORAGE_KEY);
});

test('isolated source-owned identifiers remain labels while joins, filters and exports retain stable IDs', async ({
  page,
}) => {
  test.skip(
    process.env.PATENTSAR_E2E_LLM_FIXTURE !== 'empty-synthetic',
    'Only fresh controlled adapter data, never private production or copied patents.',
  );
  const projectId = process.env.PATENTSAR_E2E_HISTORY_PROJECT_ID!;
  expect(projectId).toMatch(/^[a-f0-9]{32}$/);
  await page.goto(`/#/projects/${projectId}`);
  await expect(page.getByRole('columnheader', { name: '原文编号' })).toBeVisible();
  await expect(page.getByRole('columnheader', { name: 'Compound', exact: true })).toHaveCount(0);
  const nativeButton = page.getByRole('button', { name: '查看 Example 1 结构详情', exact: true });
  await expect(nativeButton).toBeVisible();
  await expect(nativeButton).toHaveText('Example 1');
  const row = page.locator('tr[data-compound="Compound 1"]');
  await expect(row.getByRole('button', { name: '修正 Example 1' })).toBeVisible();
  const response = await page.request.get(`/api/v1/projects/${projectId}/results`);
  expect(response.ok()).toBe(true);
  const record = (await response.json()).items.find(
    (item: { id: string }) => item.id === 'Compound 1',
  );
  expect(record).toMatchObject({
    id: 'Compound 1',
    display_id: 'Compound 1',
    identifier_label: 'Example 1',
  });
  const choices = await page.request.get(
    `/api/v1/projects/${projectId}/filter-values?column=compound`,
  );
  expect(choices.ok()).toBe(true);
  const values = (await choices.json()).items.map((item: { value: string }) => item.value);
  expect(values).toContain('Example 1');
  expect(values).not.toContain('Compound 1');
  await page.getByPlaceholder('搜索编号、靶点或活性…').fill('Example 1');
  await expect(nativeButton).toBeVisible();
  // Read-only label consumers only: drawing/save paths use their own focused
  // API/draft tests and must not trigger inference to populate this smoke test.
});

for (const width of [1672, 390]) {
  test(`real pending-source API label switches language without scientific or save writes at ${width}`, async ({
    page,
  }) => {
    test.skip(process.env.PATENTSAR_E2E_LLM_FIXTURE !== 'empty-synthetic');
    const projectId = process.env.PATENTSAR_E2E_HISTORY_PROJECT_ID!;
    const writes: string[] = [],
      errors: string[] = [];
    await page.setViewportSize({ width, height: 942 });
    page.on('pageerror', (error) => errors.push(error.message));
    await page.route('**/api/v1/**', async (route) => {
      if (route.request().method() !== 'GET') {
        writes.push(route.request().method() + ' ' + new URL(route.request().url()).pathname);
        await route.abort();
      } else await route.continue();
    });
    await page.goto(`/#/projects/${projectId}`);
    await page.getByPlaceholder('搜索编号、靶点或活性…').fill('编号待确认');
    const response = await page.request.get(
      `/api/v1/projects/${projectId}/results?q=${encodeURIComponent('编号待确认')}`,
    );
    expect(response.ok()).toBe(true);
    const data = await response.json();
    expect(data.total).toBe(1);
    const source = data.items[0];
    expect(source.identifier_label).toBeUndefined();
    expect(source).toMatchObject({
      display_id: '编号待确认 preview-source',
      structure_id: 'preview-source',
      record_kind: 'structure_only',
      activities: [],
      smiles: null,
    });
    await expect(
      page.getByRole('button', {
        name: '查看 编号待确认 preview-source 结构详情',
        exact: true,
      }),
    ).toBeVisible();
    await page.getByRole('combobox', { name: '界面语言', exact: true }).selectOption('en');
    const trigger = page.getByRole('button', {
      name: 'View Identifier unconfirmed preview-source structure details',
      exact: true,
    });
    await expect(trigger).toBeVisible();
    await expect(trigger).toHaveText('preview-source');
    await expect(trigger).toHaveAttribute('title', 'Identifier unconfirmed preview-source');
    const identity = trigger.locator('..');
    const status = identity.getByText('Identifier unconfirmed', { exact: true });
    await expect(status).toBeVisible();
    const buttonBox = await trigger.boundingBox(),
      statusBox = await status.boundingBox();
    expect(buttonBox).toBeTruthy();
    expect(statusBox).toBeTruthy();
    expect(buttonBox!.y + buttonBox!.height + 3).toBeLessThanOrEqual(statusBox!.y);
    await expect(trigger).toHaveAttribute('data-focus-key', 'detail:' + source.id);
    await trigger.click();
    await expect(
      page.getByRole('dialog', {
        name: 'Structure details · Identifier unconfirmed preview-source',
        exact: true,
      }),
    ).toBeVisible();
    await page.keyboard.press('Escape');
    await page.screenshot({
      path: test.info().outputPath(`pending-label-${width}.png`),
      fullPage: true,
    });
    await page.reload();
    // Free-text search is local view state, separate from the persisted locale.
    // Reopen the same source before checking its post-reload language and ID.
    await page.getByRole('textbox', { name: 'Search results', exact: true }).fill('编号待确认');
    await expect(trigger).toBeVisible();
    await page
      .getByRole('combobox', { name: 'Interface language', exact: true })
      .selectOption('zh-CN');
    await expect(
      page.getByRole('button', {
        name: '查看 编号待确认 preview-source 结构详情',
        exact: true,
      }),
    ).toBeVisible();
    expect(writes).toEqual([]);
    expect(errors).toEqual([]);
  });
}
