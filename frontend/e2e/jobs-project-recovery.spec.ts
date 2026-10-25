import { expect, test, type Page, type TestInfo } from '@playwright/test';
import { job as controlledJob } from '../tests/fixtures';

async function capture(page: Page, info: TestInfo, name: string) {
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth + 1)).toBe(
    true,
  );
  await page.screenshot({ path: info.outputPath(name + '.png'), animations: 'disabled' });
}

for (const width of [390, 1672]) {
  test(`one unreadable source is visible without blocking task controls at ${width}px`, async ({
    page,
  }, info) => {
    const origin = new URL(process.env.PATENTSAR_E2E_BASE_URL!);
    expect(['127.0.0.1', 'localhost', '[::1]']).toContain(origin.hostname);
    expect(Number(origin.port)).toBeGreaterThanOrEqual(18766);
    expect(Number(origin.port)).toBeLessThanOrEqual(18866);
    const writes: string[] = [],
      errors: string[] = [];
    let sourceId = '',
      sourceTitle = '',
      fault = true;
    page.on('pageerror', (error) => errors.push(error.message));
    await page.route('**/api/v1/**', async (route) => {
      const request = route.request(),
        url = new URL(request.url());
      if (request.method() !== 'GET') {
        writes.push(url.pathname);
        return route.abort();
      }
      if (url.pathname === '/api/v1/projects') {
        const response = await route.fetch();
        const body = await response.json();
        expect(body.items.length).toBeGreaterThan(0);
        sourceId = body.items[0].id;
        sourceTitle = body.items[0].title;
        if (fault)
          body.items[0] = {
            ...body.items[0],
            is_historical: true,
            acceptance: { state: 'failed', errors: ['Controlled invalid saved source'] },
            read_error: { code: 'invalid_artifact', message: 'Controlled invalid saved source' },
          };
        return route.fulfill({ response, json: body });
      }
      if (url.pathname === '/api/v1/jobs') {
        // This GET-only synthetic fixture is not a private patent or real job.
        return route.fulfill({
          json: {
            items: [
              {
                ...controlledJob,
                id: 'd'.repeat(32),
                project_id: sourceId,
                status: 'failed',
                can_resume: true,
              },
            ],
          },
        });
      }
      return route.continue();
    });
    await page.setViewportSize({ width, height: width === 390 ? 844 : 1060 });
    await page.goto('/#/projects');
    await expect(page.getByRole('status', { name: 'Results need repair' })).toBeVisible();
    await page.getByRole('button', { name: 'Tasks', exact: true }).click();
    const panel = page.locator('.jobs-page');
    const select = panel.getByRole('combobox', { name: 'Filter tasks by project' });
    await expect(select).toBeEnabled();
    await expect(panel.getByRole('button', { name: sourceTitle, exact: true })).toBeVisible();
    await expect(panel.getByRole('status', { name: 'Results need repair' })).toBeVisible();
    await expect(panel.getByRole('button', { name: 'Run extraction', exact: true })).toBeDisabled();
    await expect(
      panel.getByRole('button', { name: 'Resume extraction', exact: true }),
    ).toBeDisabled();
    await capture(page, info, 'source-error-isolated-en');
    const language = page.getByRole('combobox', { name: 'Interface language' });
    await language.selectOption('zh-CN');
    await expect(panel.getByRole('status', { name: '结果数据需修复' })).toBeVisible();
    await expect(panel.getByRole('button', { name: sourceTitle, exact: true })).toBeVisible();
    await capture(page, info, 'source-error-isolated-zh');
    // Only the intercepted GET recovers; original files are unchanged.
    fault = false;
    await panel.getByRole('button', { name: '刷新任务记录', exact: true }).click();
    await expect(panel.getByRole('status', { name: '结果数据需修复' })).toHaveCount(0);
    await expect(panel.getByRole('button', { name: '继续提取', exact: true })).toBeEnabled();
    expect(writes).toEqual([]);
    expect(errors).toEqual([]);
  });
}

// Browser-only GET faults/empty catalog responses. No source/record write,
// deletion, cancellation, resume, extraction, model or environment operation.
for (const width of [390, 800, 1672]) {
  test(`task project metadata error, retry and retained scope at ${width}px`, async ({
    page,
  }, info) => {
    const origin = new URL(process.env.PATENTSAR_E2E_BASE_URL!);
    expect(['127.0.0.1', 'localhost', '[::1]']).toContain(origin.hostname);
    expect(Number(origin.port)).toBeGreaterThanOrEqual(18766);
    expect(Number(origin.port)).toBeLessThanOrEqual(18866);
    let mode: 'fault' | 'healthy' | 'empty' = 'fault';
    const detailReads: string[] = [];
    const errors: string[] = [],
      writes: string[] = [],
      queries: (string | null)[] = [];
    page.on('pageerror', (error) => errors.push(error.message));
    await page.route('**/api/v1/**', async (route) => {
      const request = route.request(),
        url = new URL(request.url());
      if (request.method() !== 'GET') {
        writes.push(url.pathname);
        return route.abort();
      }
      if (url.pathname === '/api/v1/jobs') queries.push(url.searchParams.get('project_id'));
      if (/^\/api\/v1\/jobs\/[^/]+$/.test(url.pathname)) detailReads.push(url.pathname);
      if (url.pathname === '/api/v1/projects' && mode === 'fault') {
        return route.fulfill({
          status: 503,
          contentType: 'application/json',
          body: JSON.stringify({
            error: {
              code: 'controlled_project_read',
              message: 'Controlled project metadata read failed',
            },
          }),
        });
      }
      if (url.pathname === '/api/v1/projects' && mode === 'empty') {
        const response = await route.fetch();
        return route.fulfill({ response, json: { ...(await response.json()), items: [] } });
      }
      await route.continue();
    });
    await page.setViewportSize({ width, height: width === 390 ? 844 : 1060 });
    await page.goto('/#/jobs');
    const panel = page.locator('.jobs-page');
    const select = panel.getByRole('combobox', {
      name: /^(Filter tasks by project|筛选任务所属项目)$/,
    });
    await expect(panel.getByRole('alert')).toContainText('Controlled project metadata read failed');
    await expect(select).toBeDisabled();
    await capture(page, info, '01-initial-read-error');
    mode = 'healthy';
    await panel.getByRole('alert').getByRole('button', { name: 'Reload', exact: true }).click();
    await expect(select).toBeEnabled();
    const option = select.locator('option').nth(1);
    const id = await option.getAttribute('value'),
      title = await option.innerText();
    expect(id).toMatch(/^[a-f0-9]{32}$/);
    await select.selectOption(id!);
    await expect.poll(() => queries.at(-1)).toBe(id);
    const selectedQueries = queries.length;
    mode = 'fault';
    await panel.getByRole('button', { name: 'Refresh task records', exact: true }).click();
    await expect(panel.getByRole('alert')).toContainText('Controlled project metadata read failed');
    await expect(select).toBeDisabled();
    await expect(select).toHaveValue(id!);
    await expect(select.locator('option:checked')).toHaveText(title);
    expect(queries.slice(selectedQueries).every((query) => query === id)).toBe(true);
    await capture(page, info, '02-retained-error-en');
    const language = page.getByRole('combobox', { name: /^(Interface language|界面语言)$/ });
    await language.click();
    await page.keyboard.press('End');
    await page.keyboard.press('Enter');
    await expect(language).toHaveValue('zh-CN');
    await expect(select).toHaveValue(id!);
    await expect(select.locator('option:checked')).toHaveText(title);
    await capture(page, info, '03-retained-error-zh');
    mode = 'healthy';
    await panel.getByRole('alert').getByRole('button', { name: '重新加载', exact: true }).click();
    await expect(select).toBeEnabled();
    await expect(select).toHaveValue(id!);
    await expect(panel.getByRole('alert')).toHaveCount(0);
    await capture(page, info, '04-recovered-zh');
    // Only a successful current catalog can prove absence. This empty response
    // is simulated in the browser; no project is actually deleted.
    mode = 'empty';
    await panel.getByRole('button', { name: '刷新任务记录', exact: true }).click();
    await expect(select).toBeEnabled();
    await expect(select).toHaveValue('');
    await expect.poll(() => queries.at(-1)).toBe(null);
    mode = 'healthy';
    await panel.getByRole('button', { name: '刷新任务记录', exact: true }).click();
    await expect(select.locator('option').filter({ hasText: title })).toHaveCount(1);
    expect(errors).toEqual([]);
    expect(writes).toEqual([]);
    expect(detailReads).toEqual([]);
  });
}
