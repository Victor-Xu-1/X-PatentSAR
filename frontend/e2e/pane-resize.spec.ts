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
  const header = table.getByRole('columnheader', { name: '结构 / 编号', exact: true });
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
  const handle = page.getByRole('slider', { name: '调整结构 / 编号列宽' });
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
  await expect(handle).toHaveAttribute('aria-valuenow', '120');
  await handle.press('End');
  await expect(handle).toHaveAttribute('aria-valuenow', '480');
  await handle.dblclick();
  await expect(handle).toHaveAttribute('aria-valuenow', '164');
});
