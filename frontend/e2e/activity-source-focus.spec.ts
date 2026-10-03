import { expect, test } from '@playwright/test';
import type { Locator } from '@playwright/test';
import { decodePage, decodeResults } from '../src/api/decoders';
import type { ActivityFocus, PageData } from '../src/api/types';

const projectId = process.env.PATENTSAR_E2E_SOURCE_PROJECT_ID;
async function expectOriginalOutline(canvas: Locator, data: PageData, focus: ActivityFocus) {
  const marks = canvas.locator('[data-activity-focus]');
  await expect(marks).toHaveCount(focus.boxes.length);
  const width = data.width!,
    height = data.height!;
  for (const [index, box] of focus.boxes.entries()) {
    const mark = marks.nth(index);
    await expect(mark).toHaveAttribute('data-activity-focus', focus.activity_key);
    await expect(mark).toHaveAttribute('data-focus-compound', focus.compound_id);
    const style = await mark.evaluate((element) => ({
      left: parseFloat((element as HTMLElement).style.left),
      top: parseFloat((element as HTMLElement).style.top),
      width: parseFloat((element as HTMLElement).style.width),
      height: parseFloat((element as HTMLElement).style.height),
    }));
    expect(style.left).toBeCloseTo((100 * box[0]) / width, 4);
    expect(style.top).toBeCloseTo((100 * box[1]) / height, 4);
    expect(style.width).toBeCloseTo((100 * (box[2] - box[0])) / width, 4);
    expect(style.height).toBeCloseTo((100 * (box[3] - box[1])) / height, 4);
  }
}
test('real activity value click, same-page cell switching, refresh and cleared manual navigation', async ({
  page,
}) => {
  test.skip(!projectId, 'Requires the approved genuine original project and focus backend');
  const errors: string[] = [];
  page.on('pageerror', (error) => errors.push(error.message));
  await page.goto(`/#/projects/${projectId}?page=352&tab=original&pdfWidth=28&pdf=1`);
  const table = page.getByRole('table');
  await expect(table).toBeVisible();
  const response = await page.request.get(
    `/api/v1/projects/${projectId}/results?page=1&page_size=25`,
  );
  expect(response.ok()).toBe(true);
  const results = decodeResults(await response.json());
  const row = results.items.find((item) => item.display_id === 'Compound 2');
  expect(row, 'Approved genuine project must expose Compound 2').toBeDefined();
  expect(row!.activity_source_keys).toHaveLength(row!.activities.length);
  const ratioIndex = row!.activities.findIndex(
    (activity) =>
      activity.name === 'Cereblon HTRF ratio' &&
      String(activity.value) === '0.15' &&
      activity.page === 343,
  );
  const gradeIndex = row!.activities.findIndex(
    (activity) =>
      activity.name === 'Cereblon HTRF grade' && activity.value === '+++' && activity.page === 343,
  );
  expect(ratioIndex).toBeGreaterThanOrEqual(0);
  expect(gradeIndex).toBeGreaterThanOrEqual(0);
  const rowElement = table.locator('tbody tr').filter({
    has: page.getByLabel(`选择化合物 ${row!.display_id}`, { exact: true }),
  });
  const canvas = page.locator('.page-canvas');
  let previousKey: string | null = null;
  let previousBoxes: ActivityFocus['boxes'] | null = null;
  const originalCellBoxes = [
    [266.25, 742.2, 340.8, 763.5],
    [340.8, 742.2, 414, 763.5],
  ];
  for (const [position, index] of [ratioIndex, gradeIndex].entries()) {
    const activity = row!.activities[index]!;
    const key = row!.activity_source_keys![index]!;
    const query = new URLSearchParams({ focus_compound: row!.id, focus_activity: key });
    const source = await page.request.get(
      `/api/v1/projects/${projectId}/pages/${activity.page}?${query}`,
    );
    expect(source.ok()).toBe(true);
    const data = decodePage(await source.json());
    expect(data.activity_focus?.status).toBe('located');
    const focus = data.activity_focus!;
    expect(focus.compound_id).toBe(row!.id);
    expect(focus.activity_key).toBe(key);
    expect(focus.boxes).toHaveLength(1);
    for (const [coordinate, expected] of originalCellBoxes[position]!.entries())
      expect(focus.boxes[0]![coordinate]).toBeCloseTo(expected, 4);
    if (previousBoxes) expect(focus.boxes).not.toEqual(previousBoxes);
    const value = rowElement.locator(`button[data-activity-index="${index}"]`);
    await expect(value).toHaveText(position === 0 ? '0.15' : '+++');
    await value.click();
    await expect(page.getByLabel('原始文档页码')).toHaveValue('343');
    await expect(page).toHaveURL(new RegExp(`focusActivity=${key}`));
    await expect(page.getByRole('tab', { name: '原文视图' })).toHaveAttribute(
      'aria-selected',
      'true',
    );
    const original = page.getByRole('img', { name: '原始专利 PDF 第 343 页', exact: true });
    await expect
      .poll(() => original.evaluate((image) => (image as HTMLImageElement).naturalWidth))
      .toBeGreaterThan(0);
    await expectOriginalOutline(canvas, data, focus);
    if (previousKey)
      await expect(canvas.locator(`[data-activity-focus="${previousKey}"]`)).toHaveCount(0);
    const scroller = page.locator('.pdf-scroll');
    await expect
      .poll(async () => {
        const viewport = await scroller.boundingBox();
        const target = await canvas.locator('[data-activity-focus]').first().boundingBox();
        return Boolean(
          viewport &&
          target &&
          target.y >= viewport.y - 1 &&
          target.y + target.height <= viewport.y + viewport.height + 1,
        );
      })
      .toBe(true);
    await page.screenshot({
      path: test.info().outputPath(`0${position + 1}-real-source-cell.png`),
      fullPage: true,
    });
    await canvas
      .locator('[data-activity-focus]')
      .first()
      .screenshot({
        path: test.info().outputPath(`0${position + 1}-actual-cell-roi.png`),
      });
    previousKey = key;
    previousBoxes = focus.boxes;
  }
  expect(await table.innerText()).not.toMatch(/p\.\d+/);
  await page.reload();
  await expect(page.getByLabel('原始文档页码')).toHaveValue('343');
  await expect(canvas.locator('[data-activity-focus]')).toHaveAttribute(
    'data-activity-focus',
    previousKey!,
  );
  await expect
    .poll(() =>
      page
        .getByRole('img', { name: '原始专利 PDF 第 343 页', exact: true })
        .evaluate((image) => (image as HTMLImageElement).naturalWidth),
    )
    .toBeGreaterThan(0);
  await page.getByRole('button', { name: '文档工具', exact: true }).click();
  await page.getByLabel('放大原始文档', { exact: true }).click();
  await expect(
    page.getByRole('img', { name: '原始专利 PDF 第 343 页', exact: true }),
  ).toHaveAttribute('src', /scale=1.25$/);
  await expect(canvas.locator('[data-activity-focus]')).toHaveAttribute(
    'data-activity-focus',
    previousKey!,
  );
  await page.getByRole('button', { name: '关闭对话框', exact: true }).click();
  await page.screenshot({
    path: test.info().outputPath('03-refresh-and-zoom.png'),
    fullPage: true,
  });
  await page.getByRole('tab', { name: '结构标注' }).click();
  await expect(page).not.toHaveURL(/focusActivity|focusCompound/);
  await expect(canvas.locator('[data-activity-focus]')).toHaveCount(0);
  await page.getByRole('button', { name: '下一页原始文档' }).click();
  await expect(page.getByLabel('原始文档页码')).toHaveValue('344');
  await expect(canvas.locator('[data-activity-focus]')).toHaveCount(0);
  expect(errors).toEqual([]);
});
