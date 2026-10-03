import { expect, test } from '@playwright/test';
import type { Locator, Page } from '@playwright/test';

const projectId = process.env.PATENTSAR_E2E_SOURCE_PROJECT_ID;

async function workbench(page: Page) {
  test.skip(!projectId, 'Requires an approved real project; this suite is read-only.');
  await page.goto(`/#/projects/${projectId}?page=79&tab=original`);
  await expect(page.getByText('v0.1.0', { exact: true })).toBeVisible({ timeout: 45_000 });
  await expect(page.locator('.results-table tbody tr').first()).toBeVisible();
}

async function drag(page: Page, handle: Locator, delta: number, release = true) {
  const box = await handle.boundingBox();
  expect(box).not.toBeNull();
  await page.mouse.move(box!.x + box!.width / 2, box!.y + Math.min(30, box!.height / 2));
  await page.mouse.down();
  await page.mouse.move(box!.x + box!.width / 2 + delta, box!.y + Math.min(30, box!.height / 2), {
    steps: 8,
  });
  if (release) await page.mouse.up();
}

for (const viewport of [
  { width: 1672, height: 942 },
  { width: 1280, height: 800 },
]) {
  test(`desktop navigation collapse and both pane dividers at ${viewport.width}×${viewport.height}`, async ({
    page,
  }) => {
    const errors: string[] = [];
    page.on('pageerror', (error) => errors.push(error.message));
    await page.setViewportSize(viewport);
    await workbench(page);
    const sidebar = page.locator('#primary-sidebar');
    const expanded = (await sidebar.boundingBox())!.width;
    const tableBefore = (await page.locator('.table-scroll').boundingBox())!.width;
    await page.getByRole('button', { name: '收起导航栏', exact: true }).click();
    await expect(sidebar).toHaveCSS('width', '56px');
    await expect(page.getByRole('button', { name: '环境管理', exact: true })).toBeVisible();
    expect((await page.locator('.table-scroll').boundingBox())!.width).toBeGreaterThan(tableBefore);
    await page.reload();
    await expect(page.getByRole('button', { name: '展开导航栏', exact: true })).toBeVisible();
    await expect(sidebar).toHaveCSS('width', '56px');
    await page.getByRole('button', { name: '展开导航栏', exact: true }).click();
    expect((await sidebar.boundingBox())!.width).toBe(expanded);
    const navigation = page.getByRole('slider', { name: '调整导航栏宽度' });
    await drag(page, navigation, 64);
    await expect(navigation).toHaveAttribute('aria-valuenow', '296');
    await page.reload();
    await expect(sidebar).toHaveCSS('width', '296px');
    const beforeCancel = page.url();
    await drag(page, navigation, 32, false);
    expect((await sidebar.boundingBox())!.width).toBeGreaterThan(296);
    expect(page.url()).toBe(beforeCancel);
    await page.keyboard.press('Escape');
    await page.mouse.up();
    await expect(sidebar).toHaveCSS('width', '296px');
    await navigation.dblclick();
    await expect(sidebar).toHaveCSS('width', '232px');
    const source = page.locator('.workspace-source');
    const beforeSource = (await source.boundingBox())!.width;
    const divider = page.getByRole('slider', { name: '调整原文与结果宽度' });
    await drag(page, divider, 70);
    expect((await source.boundingBox())!.width).toBeGreaterThan(beforeSource + 55);
    const sourceWidth = await divider.getAttribute('aria-valuenow');
    await page.reload();
    await expect(divider).toHaveAttribute('aria-valuenow', sourceWidth!);
    const image = page.locator('.page-canvas > img');
    await expect
      .poll(() => image.evaluate((element) => (element as HTMLImageElement).naturalWidth))
      .toBeGreaterThan(0);
    const documentBox = (await image.boundingBox())!;
    const scrollBox = (await page.locator('.pdf-scroll').boundingBox())!;
    expect(documentBox.width).toBeLessThanOrEqual(scrollBox.width);
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth + 2)).toBe(
      true,
    );
    await page.screenshot({ path: test.info().outputPath('resizable-workbench.png') });
    expect(errors).toEqual([]);
  });
}

test('table header dividers resize actual columns without changing rows, values or selection', async ({
  page,
}) => {
  await workbench(page);
  const table = page.locator('.results-table');
  const header = table.getByRole('columnheader', { name: '原始结构 / 编号', exact: true });
  const beforeWidth = (await header.boundingBox())!.width;
  const ids = await table
    .locator('tbody tr')
    .evaluateAll((rows) => rows.map((row) => (row as HTMLElement).dataset.compound));
  const text = await table.locator('tbody tr').first().innerText();
  const select = table.locator('tbody input[type=checkbox]').first();
  await select.check();
  const requests: string[] = [];
  page.on('request', (request) => {
    if (request.url().includes('/results') || request.method() !== 'GET')
      requests.push(request.url());
  });
  const handle = page.getByRole('slider', { name: '调整原始结构 / 编号列宽' });
  expect(await table.getByRole('slider').count()).toBe(
    await table.getByRole('columnheader').count(),
  );
  await drag(page, handle, 70);
  expect((await header.boundingBox())!.width).toBeGreaterThan(beforeWidth + 55);
  const committed = (await header.boundingBox())!.width;
  await drag(page, handle, -40, false);
  await page.keyboard.press('Escape');
  await page.mouse.up();
  expect((await header.boundingBox())!.width).toBeCloseTo(committed, 0);
  await expect(select).toBeChecked();
  expect(await table.locator('tbody tr').first().innerText()).toBe(text);
  expect(
    await table
      .locator('tbody tr')
      .evaluateAll((rows) => rows.map((row) => (row as HTMLElement).dataset.compound)),
  ).toEqual(ids);
  expect(requests).toEqual([]);
  await handle.focus();
  await handle.press('Home');
  await expect(handle).toHaveAttribute('aria-valuenow', '142');
  await handle.press('End');
  await expect(handle).toHaveAttribute('aria-valuenow', '480');
  await handle.dblclick();
  await expect(handle).toHaveAttribute('aria-valuenow', '142');
});

test('mobile drawer remains usable when a desktop collapsed state is restored', async ({
  page,
}) => {
  test.skip(!projectId, 'Requires an approved real project.');
  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto(`/#/projects/${projectId}?page=79&nav=0&navWidth=288`);
  await expect(page.getByText('v0.1.0', { exact: true })).toBeVisible({ timeout: 45_000 });
  await expect(page.getByRole('slider', { name: '调整导航栏宽度' })).toHaveCount(0);
  const menu = page.getByRole('button', { name: '展开或收起导航' });
  await menu.click();
  await expect(page.getByRole('button', { name: '环境管理', exact: true })).toBeVisible();
  await expect(page.locator('.nav-item .nav-label').first()).toBeVisible();
  await menu.click();
  await expect(menu).toHaveAttribute('aria-expanded', 'false');
  await menu.click();
  await page.keyboard.press('Escape');
  await expect(menu).toBeFocused();
  await expect(menu).toHaveAttribute('aria-expanded', 'false');
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth + 2)).toBe(
    true,
  );
});
