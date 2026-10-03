import { expect, test } from '@playwright/test';
import { decodeResults } from '../src/api/decoders';
const projectId = process.env.PATENTSAR_E2E_SOURCE_PROJECT_ID;
for (const width of [1672, 390]) {
  test(`real independent columns, native horizontal scroll and frozen identity at ${width}`, async ({
    page,
  }) => {
    test.skip(!projectId, 'Requires the approved real project');
    await page.setViewportSize({ width, height: width === 1672 ? 942 : 844 });
    const errors: string[] = [];
    page.on('pageerror', (error) => errors.push(error.message));
    await page.goto(`/#/projects/${projectId}?page=79&tab=original`);
    const table = page.getByRole('table');
    await expect(table).toBeVisible();
    const path = `/api/v1/projects/${projectId}/results`;
    const first = decodeResults(
      await (await page.request.get(`${path}?page=1&page_size=25`)).json(),
    );
    const next = decodeResults(
      await (await page.request.get(`${path}?page=2&page_size=25`)).json(),
    );
    const columns = first.activity_columns!;
    expect(columns.length).toBeGreaterThan(1);
    expect(next.activity_columns).toEqual(columns);
    await expect(table.getByRole('columnheader')).toHaveCount(11 + columns.length);
    await expect(table.getByRole('columnheader', { name: '专利活性', exact: true })).toHaveCount(0);
    for (const column of columns)
      await expect(table.locator(`th[data-column="activity:${column.id}"]`)).toContainText(
        column.name,
      );
    const scroller = page.locator('.table-scroll');
    expect(await scroller.evaluate((element) => element.scrollWidth > element.clientWidth)).toBe(
      true,
    );
    const identity = table.locator('tbody .frozen-structure').first();
    const editor = table.locator('tbody .frozen-edit').first();
    const before = await identity.boundingBox();
    await scroller.focus();
    for (let step = 0; step < 15; step++) await page.keyboard.press('ArrowRight');
    await expect
      .poll(() => scroller.evaluate((element) => element.scrollLeft))
      .toBeGreaterThan(100);
    expect((await identity.boundingBox())!.x).toBeCloseTo(before!.x, 0);
    const outer = await scroller.boundingBox(),
      editBox = await editor.boundingBox();
    expect(editBox!.x + editBox!.width).toBeLessThanOrEqual(outer!.x + outer!.width + 1);
    expect(editBox!.x + editBox!.width).toBeGreaterThan(outer!.x + outer!.width - 20);
    await page.screenshot({
      path: test.info().outputPath(`02-horizontal-${width}.png`),
      fullPage: true,
    });
    await scroller.evaluate((element, narrow) => {
      // On small screens the frozen edit column covers the first resize handle at scrollLeft=0.
      // Bring that handle into the visible, non-frozen area before testing a real pointer drag.
      element.scrollLeft = narrow ? 120 : 0;
    }, width < 600);
    const column = table.locator('th.activity-value-column').first();
    const handle = column.getByRole('slider');
    const initial = Number(await handle.getAttribute('aria-valuenow'));
    const box = await handle.boundingBox();
    await page.mouse.move(box!.x + box!.width / 2, box!.y + box!.height / 2);
    await page.mouse.down();
    await page.mouse.move(box!.x + box!.width / 2 + 35, box!.y + box!.height / 2, { steps: 4 });
    await page.mouse.up();
    expect(Number(await handle.getAttribute('aria-valuenow'))).toBeGreaterThan(initial + 20);
    await page.getByLabel(`选择化合物 ${first.items[0]!.display_id}`, { exact: true }).check();
    await expect(
      page.getByLabel(`选择化合物 ${first.items[0]!.display_id}`, { exact: true }),
    ).toBeChecked();
    await scroller.evaluate((element) => {
      element.scrollTop = 400;
    });
    const head = await table.locator('th.activity-value-column').first().boundingBox();
    expect(head!.y).toBeCloseTo((await scroller.boundingBox())!.y, 0);
    await scroller.evaluate((element) => {
      element.scrollTop = 0;
    });
    const activity = first.items[0]!.activities.find((value) => value.page !== null)!;
    const source = page
      .getByLabel(`${first.items[0]!.display_id} ${activity.name} 活性来源第 ${activity.page} 页`, {
        exact: true,
      })
      .first();
    await source.click();
    await expect(page.getByLabel('原始文档页码')).toHaveValue(String(activity.page));
    const original = page.getByRole('img', {
      name: `原始专利 PDF 第 ${activity.page} 页`,
      exact: true,
    });
    await expect
      .poll(() => original.evaluate((element) => (element as HTMLImageElement).naturalWidth))
      .toBeGreaterThan(0);
    await page.screenshot({
      path: test.info().outputPath(`01-independent-columns-${width}.png`),
      fullPage: true,
    });
    expect(errors).toEqual([]);
  });
}
