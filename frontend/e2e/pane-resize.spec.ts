import { expect, test } from '@playwright/test';
import type { Locator, Page } from '@playwright/test';

const projectId = process.env.PATENTSAR_E2E_SOURCE_PROJECT_ID;

async function workbench(page: Page) {
  test.skip(!projectId, 'Requires an approved real project; this suite is read-only.');
  await page.goto(`/#/projects/${projectId}?tab=original`);
  await expect(page.getByRole('button', { name: '上传 PDF', exact: true })).toBeEnabled({
    timeout: 45_000,
  });
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

test('table header dividers resize actual columns without changing rows, values or selection', async ({
  page,
}) => {
  await workbench(page);
  const table = page.locator('.results-table');
  await expect(table.getByRole('columnheader', { name: '#', exact: true })).toHaveCount(0);
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
  expect(await table.getByRole('slider').count()).toBe(
    await table.getByRole('columnheader').count(),
  );
  for (const [label, initial] of [
    ['Compound', 100],
    ['结构', 96],
  ] as const) {
    const header = table.getByRole('columnheader', { name: label, exact: true });
    const beforeWidth = (await header.boundingBox())!.width;
    const handle = page.getByRole('slider', { name: `调整${label}列宽` });
    await drag(page, handle, 70);
    expect((await header.boundingBox())!.width).toBeGreaterThan(beforeWidth + 55);
    const committed = (await header.boundingBox())!.width;
    await drag(page, handle, -40, false);
    await page.keyboard.press('Escape');
    await page.mouse.up();
    expect((await header.boundingBox())!.width).toBeCloseTo(committed, 0);
    await handle.focus();
    await handle.press('Home');
    await expect(handle).toHaveAttribute('aria-valuenow', '88');
    await handle.press('End');
    await expect(handle).toHaveAttribute('aria-valuenow', '480');
    await handle.dblclick();
    await expect(handle).toHaveAttribute('aria-valuenow', String(initial));
  }
  await expect(select).toBeChecked();
  expect(await table.locator('tbody tr').first().innerText()).toBe(text);
  expect(
    await table
      .locator('tbody tr')
      .evaluateAll((rows) => rows.map((row) => (row as HTMLElement).dataset.compound)),
  ).toEqual(ids);
  expect(requests).toEqual([]);
});

test('separate compound and crop controls open actual details and the correction draft', async ({
  page,
}) => {
  await workbench(page);
  const row = page.locator('.results-table tbody tr').first();
  const identity = row.locator('.frozen-compound');
  const crop = row.locator('.frozen-structure');
  expect(await identity.locator('img').count()).toBe(0);
  await expect(crop.getByRole('img')).toBeVisible();
  expect(await crop.innerText()).toBe('');
  const label = await identity.getByRole('button').innerText();
  await identity.getByRole('button').click();
  const details = page.getByRole('dialog', { name: `结构详情 · ${label}`, exact: true });
  await expect(details).toBeVisible();
  const original = details.getByRole('img', { name: `${label} 的原始结构裁图`, exact: true });
  await expect
    .poll(() => original.evaluate((element) => (element as HTMLImageElement).naturalWidth))
    .toBeGreaterThan(0);
  await page.getByRole('button', { name: '关闭对话框', exact: true }).click();
  await expect(identity.getByRole('button')).toBeFocused();
  await crop.getByRole('button').click();
  await expect(details).toBeVisible();
  await page.getByRole('button', { name: '关闭对话框', exact: true }).click();
  await expect(crop.getByRole('button')).toBeFocused();
  await row.getByLabel(`修正 ${label}`, { exact: true }).click();
  const correction = page.getByRole('dialog', { name: `在线修正 · ${label}`, exact: true });
  await expect(correction.getByLabel('修正化合物编号')).toHaveValue(label);
  await expect(correction.getByRole('button', { name: '保存修正', exact: true })).toBeEnabled();
  await correction.getByRole('button', { name: '取消', exact: true }).click();
  await expect(row.getByLabel(`修正 ${label}`, { exact: true })).toBeFocused();
  await page.locator('.table-scroll').evaluate((element) => {
    element.scrollLeft = 0;
  });
  await page.screenshot({ path: test.info().outputPath('01-compound-column.png'), fullPage: true });
});
