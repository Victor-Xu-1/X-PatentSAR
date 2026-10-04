import { expect, test } from '@playwright/test';
import type { Filters } from '../src/api/types';
import { decodeResults } from '../src/api/decoders';
import { decodeFilterValues } from '../src/api/filterValueDecoders';
import { activityColumnContext, activityColumnLabel } from '../src/model/activityColumns';

const projectId = process.env.PATENTSAR_E2E_SOURCE_PROJECT_ID;
test('real Excel-like column controls, project-wide query and safe current-page copy', async ({
  page,
  context,
}) => {
  test.skip(
    !projectId,
    'Requires controller-owned integrated service and approved original project; read-only',
  );
  const errors: string[] = [];
  page.on('pageerror', (error) => errors.push(error.message));
  await page.goto(`/#/projects/${projectId}?page=79&tab=original&pdfWidth=28`);
  const table = page.getByRole('table');
  await expect(table).toBeVisible();
  await expect
    .poll(() => page.evaluate(() => document.documentElement.scrollHeight - innerHeight))
    .toBeLessThanOrEqual(2);
  const endpoint = `/api/v1/projects/${projectId}/results`;
  const original = decodeResults(
    await (await page.request.get(`${endpoint}?page=1&page_size=25`)).json(),
  );
  expect(original.activity_columns?.length).toBeGreaterThan(0);
  const activity = original.activity_columns![0]!;
  const choiceEndpoint = `/api/v1/projects/${projectId}/filter-values`;
  const choiceResponse = await page.request.get(
    `${choiceEndpoint}?${new URLSearchParams({ column: `activity:${activity.id}`, page: '1', page_size: '200' })}`,
  );
  expect(choiceResponse.ok()).toBe(true);
  const choices = decodeFilterValues(await choiceResponse.json());
  expect(choices.items.length, 'Dedicated full-project choices must be available').toBeGreaterThan(
    0,
  );
  const value = choices.items[0]!.value;
  const name = [activityColumnLabel(activity), activityColumnContext(activity)]
    .filter(Boolean)
    .join(' · ');
  const filters: Partial<Filters> = {
    sort_column: 'compound',
    sort_direction: 'desc',
    column_filters: [
      { column: `activity:${activity.id}`, op: 'in', values: [value], include_empty: false },
    ],
  };
  await page.getByRole('button', { name: 'Compound 列选项', exact: true }).click();
  await page.getByRole('button', { name: '降序', exact: true }).click();
  await expect(table.locator('th[data-column="compound"]')).toHaveAttribute(
    'aria-sort',
    'descending',
  );
  await expect(page.locator('.results-content')).toHaveAttribute('aria-busy', 'false');
  await page.getByRole('button', { name: `${name} 列选项`, exact: true }).click();
  await expect(page.getByLabel('全选筛选取值', { exact: true })).toBeEnabled();
  await page.getByLabel('全选筛选取值', { exact: true }).uncheck();
  await page.getByLabel(`筛选值 ${value}`, { exact: true }).check();
  const applied = page.waitForResponse((response) => {
    const url = new URL(response.url());
    return (
      url.pathname === endpoint &&
      url.searchParams.get('column_filters') === JSON.stringify(filters.column_filters)
    );
  });
  await page.getByRole('button', { name: '确定', exact: true }).click();
  expect((await applied).ok()).toBe(true);
  await expect(page.locator('.results-content')).toHaveAttribute('aria-busy', 'false');
  const query = new URLSearchParams({
    page: '1',
    page_size: '25',
    column_filters: JSON.stringify(filters.column_filters),
    sort_column: 'compound',
    sort_direction: 'desc',
  });
  const queried = decodeResults(await (await page.request.get(`${endpoint}?${query}`)).json());
  expect(queried.activity_columns).toEqual(original.activity_columns);
  const rowIds = () =>
    table
      .locator('tbody tr')
      .evaluateAll((rows) => rows.map((row) => (row as HTMLElement).dataset.compound));
  await expect.poll(rowIds).toEqual(queried.items.map((row) => row.id));
  const routedHash = await page.evaluate(() => location.hash);
  const routeQuery = new URLSearchParams(routedHash.split('?')[1]);
  expect(JSON.parse(routeQuery.get('column_filters')!)).toEqual(filters.column_filters);
  expect(routeQuery.get('sort_column')).toBe('compound');
  expect(routeQuery.get('sort_direction')).toBe('desc');
  await page.reload();
  await expect.poll(rowIds).toEqual(queried.items.map((row) => row.id));
  const selected = queried.items[0]!;
  await page.getByLabel(`选择化合物 ${selected.display_id}`, { exact: true }).check();
  await page.getByRole('button', { name: 'Compound 列选项', exact: true }).click();
  await page.getByRole('button', { name: '隐藏此列', exact: true }).click();
  await expect(table.locator('th[data-column="compound"]')).toHaveCount(0);
  await page.getByRole('button', { name: '显示列', exact: true }).click();
  await page.getByLabel('显示列 Compound', { exact: true }).check();
  await page.getByLabel('显示列 MW', { exact: true }).uncheck();
  await page.keyboard.press('Escape');
  await expect(table.locator('th[data-column="property:molecular_weight"]')).toHaveCount(0);
  await expect(table.locator('tbody td[data-property="molecular_weight"]')).toHaveCount(0);
  await expect(page.getByLabel(`选择化合物 ${selected.display_id}`, { exact: true })).toBeChecked();
  await context.grantPermissions(['clipboard-read', 'clipboard-write']);
  await page.getByRole('button', { name: '复制当前页所选行 (1)', exact: true }).click();
  const copied = await page.evaluate(() => navigator.clipboard.readText());
  expect(copied.split('\n')).toHaveLength(2);
  expect(copied).toContain(selected.display_id);
  expect(copied.split('\n')[0]!.split('\t')).not.toContain('MW');
  await page.getByRole('button', { name: '显示列', exact: true }).click();
  await page.getByRole('button', { name: '显示全部列', exact: true }).click();
  await page.keyboard.press('Escape');
  const slider = table.getByRole('slider', { name: '调整Compound列宽', exact: true });
  const previousWidth = Number(await slider.getAttribute('aria-valuenow'));
  await slider.focus();
  await page.keyboard.press('ArrowRight');
  await expect(slider).toHaveAttribute('aria-valuenow', String(previousWidth + 8));
  const source = table
    .locator('tbody tr')
    .first()
    .getByRole('button', { name: /活性来源第/ })
    .first();
  const label = await source.getAttribute('aria-label');
  const sourcePage = Number(label!.match(/第 (\d+) 页/)![1]);
  await source.click();
  await expect(page.getByLabel('原始文档页码', { exact: true })).toHaveValue(String(sourcePage));
  await page.getByRole('button', { name: '清除列筛选', exact: true }).click();
  await page.getByRole('button', { name: '取消列排序', exact: true }).click();
  await expect.poll(rowIds).toEqual(original.items.map((row) => row.id));
  await expect
    .poll(() => page.evaluate(() => document.documentElement.scrollHeight - innerHeight))
    .toBeLessThanOrEqual(2);
  await page.screenshot({
    path: test.info().outputPath('01-excel-column-controls.png'),
    fullPage: true,
  });
  expect(errors).toEqual([]);
});
