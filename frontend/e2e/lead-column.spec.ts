import { expect, test } from '@playwright/test';
import type { Page } from '@playwright/test';
import { decodeProject, decodeResults } from '../src/api/decoders';
import type { LeadAssessment } from '../src/api/leadTypes';
import type { ColumnFilter, Compound } from '../src/api/types';
import { leadColumnValue } from '../src/model/resultColumns';

const fixtureId = process.env.PATENTSAR_E2E_HISTORY_PROJECT_ID;
const fixtureTitle = 'CI controlled historical adapter fixture (not extraction evidence)';
const assessment: LeadAssessment = {
  status: 'selected',
  rank: 1,
  score: 84.75,
  activity_coverage: 0.75,
  components: { potency: 91, coverage: 75, physchem: 80, admet: 70, diversity: 90 },
  reasons: ['Controlled synthetic coverage', 'Controlled synthetic diversity'],
  warnings: ['Research prioritization, not experimentally validated Leads'],
  scaffold: 'c1ccccc1',
  nearest_similarity: 0.35,
  policy_version: '1',
  review_only: true,
};
type ResponseMode = 'ready' | 'legacy' | 'invalid' | 'failure' | 'empty';

// Reuse the project's isolated adapter/PDF fixture, never a private patent or
// production project. Route data verifies UI contracts only; the controller
// separately verifies the real backend prioritization, persistence and API.
async function controlledWorkspace(page: Page) {
  test.skip(!fixtureId, 'Requires tools/prepare_browser_fixture.py isolated synthetic state.');
  expect((await page.request.get('/api/v1/session')).ok()).toBe(true);
  const projectResponse = await page.request.get(`/api/v1/projects/${fixtureId}`);
  expect(projectResponse.ok()).toBe(true);
  const project = decodeProject(await projectResponse.json());
  expect(project.title, 'Only the explicit controlled fixture may enter this browser test').toBe(
    fixtureTitle,
  );
  const endpoint = `/api/v1/projects/${fixtureId}/results`;
  const response = await page.request.get(`${endpoint}?page=1&page_size=100`);
  expect(response.ok()).toBe(true);
  const original = decodeResults(await response.json());
  expect(original.total).toBe(30);
  const ranks = [8, 1, 2, 3, 4, 5, 6, 7];
  const rows: Compound[] = original.items.map((row, index) => ({
    ...row,
    lead: {
      ...assessment,
      status:
        index < 8
          ? 'selected'
          : index === 8
            ? 'stale'
            : index === 9
              ? 'ineligible'
              : 'not_selected',
      rank: index < 8 ? ranks[index]! : null,
      score: index === 8 ? null : assessment.score,
    },
  }));
  const state = { mode: 'ready' as ResponseMode, requests: [] as URL[] };
  await page.route(`**${endpoint}?**`, async (route) => {
    const url = new URL(route.request().url());
    state.requests.push(url);
    if (state.mode === 'failure') {
      await route.fulfill({
        status: 500,
        json: { error: { code: 'controlled_error', message: 'Controlled Lead query failed' } },
      });
      return;
    }
    const filters = JSON.parse(url.searchParams.get('column_filters') ?? '[]') as ColumnFilter[];
    let visible = state.mode === 'empty' ? [] : [...rows];
    for (const filter of filters.filter((item) => item.column === 'lead')) {
      visible = visible.filter((row) => {
        const value = leadColumnValue(row.lead);
        if (filter.op === 'in')
          return filter.values?.includes(value) || (!value && filter.include_empty);
        if (filter.op === 'empty') return !value;
        if (filter.op === 'not_empty') return Boolean(value);
        throw new Error('Unexpected synthetic Lead query condition');
      });
    }
    if (url.searchParams.get('sort_column') === 'lead') {
      const direction = url.searchParams.get('sort_direction') === 'desc' ? -1 : 1;
      visible.sort((first, second) => {
        const a = leadColumnValue(first.lead),
          b = leadColumnValue(second.lead);
        return !a ? (b ? 1 : 0) : !b ? -1 : direction * a.localeCompare(b);
      });
    }
    const pageNumber = Number(url.searchParams.get('page') ?? '1');
    const pageSize = Number(url.searchParams.get('page_size') ?? '25');
    const items = visible.slice((pageNumber - 1) * pageSize, pageNumber * pageSize).map((row) => {
      if (state.mode === 'legacy') {
        const { lead: _lead, ...legacy } = row;
        return legacy;
      }
      return state.mode === 'invalid' ? { ...row, lead: { ...assessment, rank: null } } : row;
    });
    await route.fulfill({
      json: { ...original, items, total: visible.length, page: pageNumber, page_size: pageSize },
    });
  });
  await page.route(`**/api/v1/projects/${fixtureId}/filter-values?**`, async (route) => {
    const url = new URL(route.request().url());
    if (url.searchParams.get('column') !== 'lead') {
      await route.continue();
      return;
    }
    const search = (url.searchParams.get('search') ?? '').toLowerCase();
    const items = Array.from({ length: 8 }, (_, index) => ({
      value: `Lead ${index + 1}`,
      count: 1,
    })).filter((item) => item.value.toLowerCase().includes(search));
    await route.fulfill({
      json: {
        column: 'lead',
        kind: 'text',
        items,
        total: items.length,
        page: 1,
        page_size: 200,
        empty_count: 22,
        matching_rows: 30,
      },
    });
  });
  const errors: string[] = [];
  page.on('pageerror', (error) => errors.push(error.message));
  await page.goto(`/#/projects/${fixtureId}?page=1&tab=original`);
  await expect(page.getByRole('table')).toBeVisible();
  return { state, rows, errors };
}

test('controlled Lead column retains backend ranks, Excel controls, pagination and visible-only copy', async ({
  page,
  context,
}, testInfo) => {
  const { state, rows, errors } = await controlledWorkspace(page);
  const table = page.getByRole('table');
  const leadCells = table.locator('tbody td[data-column="lead"]');
  await expect(leadCells.first()).toHaveText('Lead 8');
  await expect(leadCells.nth(1)).toHaveText('Lead 1');
  await expect(leadCells.nth(8)).toHaveText('待更新');
  await expect(leadCells.nth(9)).toHaveText('—');
  await expect(leadCells.first()).toHaveCSS('text-align', 'center');
  await expect(leadCells.first()).toHaveAttribute('title', /候选优先级 84\.8 \/ 100/);
  await expect(leadCells.first()).toHaveAttribute('title', /Controlled synthetic coverage/);
  await expect(leadCells.first()).toHaveAttribute('title', /不代表实验验证/);
  expect(
    await table
      .locator('th')
      .evaluateAll((headers) =>
        headers.slice(0, 4).map((header) => (header as HTMLElement).dataset.column),
      ),
  ).toEqual(['select', 'compound', 'structure', 'lead']);
  await page.screenshot({ path: testInfo.outputPath('lead-minimal-desktop.png'), fullPage: true });

  await page.getByRole('button', { name: '下一页结果', exact: true }).click();
  await expect(table.locator('tbody tr')).toHaveCount(5);
  await expect(table.locator('.lead-badge')).toHaveCount(0);
  await page.getByRole('button', { name: '上一页结果', exact: true }).click();
  await expect(leadCells.first()).toHaveText('Lead 8');
  const slider = table.getByRole('slider', { name: '调整Lead列宽', exact: true });
  const width = Number(await slider.getAttribute('aria-valuenow'));
  await slider.focus();
  await page.keyboard.press('ArrowRight');
  await expect(slider).toHaveAttribute('aria-valuenow', String(width + 8));
  const handle = await slider.boundingBox();
  expect(handle).not.toBeNull();
  await page.mouse.move(handle!.x + handle!.width / 2, handle!.y + handle!.height / 2);
  await page.mouse.down();
  await page.mouse.move(handle!.x + handle!.width / 2 + 24, handle!.y + handle!.height / 2);
  await page.mouse.up();
  await expect(slider).toHaveAttribute('aria-valuenow', String(width + 32));
  await page.getByRole('button', { name: 'Lead 列选项', exact: true }).click();
  await page.getByRole('button', { name: '隐藏此列', exact: true }).click();
  await expect(table.locator('th[data-column="lead"],td[data-column="lead"]')).toHaveCount(0);
  await page.getByRole('button', { name: '显示列', exact: true }).click();
  await page.getByLabel('显示列 Lead', { exact: true }).check();
  await page.keyboard.press('Escape');
  await expect(slider).toHaveAttribute('aria-valuenow', String(width + 32));

  await context.grantPermissions(['clipboard-read', 'clipboard-write']);
  await page.getByLabel(`选择化合物 ${rows[0]!.display_id}`, { exact: true }).check();
  await page.getByRole('button', { name: '复制当前页所选行 (1)', exact: true }).click();
  const copied = await page.evaluate(() => navigator.clipboard.readText());
  expect(copied.split('\n')).toHaveLength(2);
  const headings = copied.split('\n')[0]!.split('\t');
  expect(copied.split('\n')[1]!.split('\t')[headings.indexOf('Lead')]).toBe('Lead 8');
  await page.getByLabel(`选择化合物 ${rows[0]!.display_id}`, { exact: true }).uncheck();
  await page.getByRole('button', { name: 'Lead 列选项', exact: true }).click();
  await page.getByRole('button', { name: '升序', exact: true }).click();
  await expect(table.locator('th[data-column="lead"]')).toHaveAttribute('aria-sort', 'ascending');
  await expect(leadCells.first()).toHaveText('Lead 1');
  expect(state.requests.some((url) => url.searchParams.get('sort_column') === 'lead')).toBe(true);
  await page.getByRole('button', { name: 'Lead 列选项', exact: true }).click();
  await expect(page.getByLabel('筛选值 Lead 3', { exact: true })).toBeVisible();
  await page.getByLabel('全选筛选取值', { exact: true }).uncheck();
  await page.getByLabel('筛选值 Lead 3', { exact: true }).check();
  await page.getByRole('button', { name: '确定', exact: true }).click();
  await expect(table.locator('tbody tr')).toHaveCount(1);
  await expect(leadCells.first()).toHaveText('Lead 3');
  const routed = new URLSearchParams((await page.evaluate(() => location.hash)).split('?')[1]);
  expect(JSON.parse(routed.get('column_filters')!)).toEqual([
    { column: 'lead', op: 'in', values: ['Lead 3'], include_empty: false },
  ]);
  await page.reload();
  await expect(table.locator('tbody tr')).toHaveCount(1);
  await expect(leadCells.first()).toHaveText('Lead 3');
  expect(errors).toEqual([]);
});

for (const viewport of [
  { width: 1280, height: 800 },
  { width: 390, height: 844 },
]) {
  test(`controlled Lead column stays centered and scrollable at ${viewport.width}px`, async ({
    page,
  }, testInfo) => {
    await page.setViewportSize(viewport);
    const { errors } = await controlledWorkspace(page);
    const cell = page.getByRole('table').locator('tbody td[data-column="lead"]').first();
    await cell.scrollIntoViewIfNeeded();
    await expect(cell).toHaveText('Lead 8');
    await expect(cell).toHaveCSS('text-align', 'center');
    const badge = cell.locator('.lead-badge');
    await expect(badge).toBeVisible();
    const bounds = await cell.boundingBox(),
      label = await badge.boundingBox();
    expect(bounds).not.toBeNull();
    expect(label).not.toBeNull();
    expect(
      Math.abs(bounds!.x + bounds!.width / 2 - (label!.x + label!.width / 2)),
    ).toBeLessThanOrEqual(1);
    expect(
      await page.evaluate(() => document.documentElement.scrollWidth - innerWidth),
    ).toBeLessThanOrEqual(2);
    await page.screenshot({
      path: testInfo.outputPath(`lead-${viewport.width}.png`),
      fullPage: true,
    });
    expect(errors).toEqual([]);
  });
}

test('controlled old, empty, invalid and failed Lead responses never become successful nominations', async ({
  page,
}) => {
  const { state, errors } = await controlledWorkspace(page);
  state.mode = 'legacy';
  await page.reload();
  await expect(page.getByRole('table')).toBeVisible();
  await expect(page.locator('.lead-badge')).toHaveCount(0);
  await expect(page.locator('tbody td[data-column="lead"]').first()).toHaveText('—');
  state.mode = 'invalid';
  await page.reload();
  await expect(page.getByRole('alert')).toContainText('API 数据格式不符合契约');
  await expect(page.getByRole('table')).toBeHidden();
  await expect(page.getByRole('button', { name: '复制当前页', exact: true })).toBeDisabled();
  state.mode = 'failure';
  await page.reload();
  await expect(page.getByRole('alert')).toContainText('Controlled Lead query failed');
  await expect(page.getByRole('table')).toBeHidden();
  state.mode = 'empty';
  await page.reload();
  await expect(page.getByRole('table')).toBeVisible();
  await expect(page.getByRole('columnheader', { name: 'Lead', exact: true })).toBeVisible();
  await expect(page.getByText('暂无匹配的提取结果', { exact: true })).toBeVisible();
  await expect(page.locator('.lead-badge')).toHaveCount(0);
  expect(errors).toEqual([]);
});
