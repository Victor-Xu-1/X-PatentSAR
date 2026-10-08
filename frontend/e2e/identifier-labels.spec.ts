import { expect, test } from '@playwright/test';

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
  await page.getByRole('searchbox').fill('Example 1');
  await expect(nativeButton).toBeVisible();
  // Read-only label consumers only: drawing/save paths use their own focused
  // API/draft tests and must not trigger inference to populate this smoke test.
});
