import { expect, test } from '@playwright/test';
import type { Page } from '@playwright/test';
import type { Job, Project, Results } from '../src/api/types';

const historyId = process.env.PATENTSAR_E2E_HISTORY_PROJECT_ID;
const sourceId = process.env.PATENTSAR_E2E_SOURCE_PROJECT_ID;
const failedJobId = process.env.PATENTSAR_E2E_FAILED_JOB_ID;
async function fittedPage(page: Page) {
  const image = page.locator('.page-canvas > img');
  await expect(image).toBeVisible();
  await expect
    .poll(() => image.evaluate((element) => (element as HTMLImageElement).naturalWidth))
    .toBeGreaterThan(0);
  const frame = await page.locator('.pdf-scroll').boundingBox();
  const box = await image.boundingBox();
  expect(box).not.toBeNull();
  expect(frame).not.toBeNull();
  expect(box!.width).toBeGreaterThan(100);
  expect(box!.width).toBeLessThanOrEqual(frame!.width);
  expect(box!.x).toBeGreaterThanOrEqual(frame!.x);
  expect(box!.x + box!.width).toBeLessThanOrEqual(frame!.x + frame!.width);
  return box!;
}
for (const viewport of [
  { width: 1672, height: 942 },
  { width: 1280, height: 800 },
]) {
  test(`measured result-first table, splitter and refresh at ${viewport.width}×${viewport.height}`, async ({
    page,
  }) => {
    test.skip(
      !historyId,
      'Requires the approved isolated project used by the existing result gates',
    );
    await page.setViewportSize(viewport);
    await page.goto(`/#/projects/${historyId}`);
    await expect(page.locator('.results-table tbody tr').first()).toBeVisible();
    const table = await page.locator('.table-scroll').boundingBox();
    const source = await page.locator('.workspace-source').boundingBox();
    const result = await page.locator('.workspace-results').boundingBox();
    expect(table!.height / viewport.height).toBeGreaterThanOrEqual(0.72);
    await expect(page.locator('.workspace-source')).toHaveCount(1);
    await expect(page.locator('.workspace-results')).toHaveCount(1);
    await expect(page.getByLabel('项目真实统计')).toHaveCount(0);
    const pane = await page.locator('.results-pane').boundingBox();
    const pagination = await page.locator('.pagination').boundingBox();
    expect(pane).not.toBeNull();
    expect(pagination).not.toBeNull();
    expect(
      pagination!.y + pagination!.height,
      'Pagination must not be clipped by the results pane',
    ).toBeLessThanOrEqual(pane!.y + pane!.height);
    expect(
      pane!.y + pane!.height,
      'The desktop results pane must fit the viewport',
    ).toBeLessThanOrEqual(viewport.height);
    const visibleHeight =
      Math.min(table!.y + table!.height, pane!.y + pane!.height, viewport.height) -
      Math.max(table!.y, pane!.y, 0);
    expect(
      visibleHeight / viewport.height,
      'The measured table area must actually be visible',
    ).toBeGreaterThanOrEqual(0.72);
    expect(source!.width / (source!.width + result!.width)).toBeGreaterThanOrEqual(0.25);
    expect(source!.width / (source!.width + result!.width)).toBeLessThanOrEqual(0.3);
    const separator = page.getByRole('slider', { name: '调整原文与结果宽度' });
    await separator.focus();
    await separator.press('ArrowRight');
    await expect(separator).toHaveAttribute('aria-valuenow', '30');
    await page.reload();
    await expect(separator).toHaveAttribute('aria-valuenow', '30');
    const rect = await separator.boundingBox();
    await page.mouse.move(rect!.x + rect!.width / 2, rect!.y + 50);
    await page.mouse.down();
    await page.mouse.move(rect!.x + 70, rect!.y + 50);
    await page.mouse.up();
    await expect.poll(() => separator.getAttribute('aria-valuenow')).not.toBe('30');
    await page.getByRole('button', { name: '收起原文，结果全宽' }).click();
    await expect(page.locator('.workspace-source')).toHaveCount(0);
    await page.reload();
    await expect(page.getByRole('button', { name: '展开原文' })).toBeVisible();
    await page.getByRole('button', { name: '全屏工作区' }).click();
    await expect(page.locator('.workspace-layout')).toHaveClass(/is-fullscreen/);
    await page.keyboard.press('Escape');
    await expect(page.locator('.workspace-layout')).not.toHaveClass(/is-fullscreen/);
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth + 2)).toBe(
      true,
    );
    await test.info().attach('measured-layout', {
      body: JSON.stringify({ viewport, table, source, result }),
      contentType: 'application/json',
    });
  });
}
test('actual job parameters can expand without pushing desktop panes below the viewport', async ({
  page,
}) => {
  test.skip(!failedJobId, 'Requires the existing controlled real CLI failure');
  await page.goto('/#/jobs');
  await expect(page.getByRole('button', { name: '上传 PDF', exact: true })).toBeEnabled();
  const response = await page.request.get(`/api/v1/jobs/${encodeURIComponent(failedJobId!)}`);
  expect(response.ok()).toBe(true);
  const job = (await response.json()) as Job;
  expect(job.status).toBe('failed');
  await page.goto(`/#/projects/${job.project_id}`);
  await page.getByRole('button', { name: '任务详情' }).click();
  const options = page.locator('.job-options-record');
  await expect(options).toBeVisible();
  for (const viewport of [
    { width: 1672, height: 942 },
    { width: 1280, height: 800 },
  ]) {
    await page.setViewportSize(viewport);
    await expect(options).toHaveAttribute('open', '');
    for (const selector of ['.results-pane', '.pdf-pane']) {
      const pane = await page.locator(selector).boundingBox();
      expect(pane).not.toBeNull();
      expect(pane!.height).toBeGreaterThan(300);
      expect(
        pane!.y + pane!.height,
        `${selector} must include actual expanded job height`,
      ).toBeLessThanOrEqual(viewport.height);
    }
  }
});

test('actual original fit-width, resizing, source jump and exact annotation geometry', async ({
  page,
}) => {
  test.skip(
    !sourceId,
    'Set PATENTSAR_E2E_SOURCE_PROJECT_ID to an approved project with its actual original PDF',
  );
  await page.goto(`/#/projects/${sourceId}`);
  await expect(page.getByRole('button', { name: '上传 PDF', exact: true })).toBeEnabled();
  const projectResponse = await page.request.get(`/api/v1/projects/${sourceId}`);
  const project = (await projectResponse.json()) as Project;
  expect(
    project.pdf.available,
    'Source acceptance requires the actual original, not historical OCR',
  ).toBe(true);
  expect(
    project.first_structure_page,
    'The source fixture must provide a genuine structure page',
  ).toBeGreaterThan(0);
  await expect(page.getByLabel('原始文档页码')).toHaveValue(String(project.first_structure_page));
  const before = await fittedPage(page);
  const separator = page.getByRole('slider', { name: '调整原文与结果宽度' });
  await separator.focus();
  await separator.press('ArrowRight');
  await separator.press('ArrowRight');
  const after = await fittedPage(page);
  expect(after.width).toBeGreaterThan(before.width);
  await page.getByRole('button', { name: '文档工具' }).click();
  await page.getByLabel('放大原始文档').click();
  await expect(page.getByLabel('文档缩放比例')).toHaveText('125%');
  await page.getByLabel('重置文档缩放').click();
  await page.keyboard.press('Escape');
  await fittedPage(page);
  const response = await page.request.get(
    `/api/v1/projects/${sourceId}/results?page=1&page_size=25`,
  );
  const results = (await response.json()) as Results;
  const row = results.items.find(
    (compound) => compound.source.page !== null && compound.source.bbox !== null,
  );
  expect(row, 'The approved source project must include an actual located structure').toBeTruthy();
  await page.getByRole('button', { name: '收起原文，结果全宽' }).click();
  await page
    .locator('.results-table tbody tr')
    .filter({ has: page.getByLabel(`选择化合物 ${row!.display_id}`, { exact: true }) })
    .getByRole('button', { name: /结构来源第 \d+ 页$/ })
    .click();
  await expect(page.getByRole('tab', { name: '结构标注' })).toHaveAttribute(
    'aria-selected',
    'true',
  );
  await expect(page.getByLabel('原始文档页码')).toHaveValue(String(row!.source.page));
  await fittedPage(page);
  const annotation = page.locator('.annotation-box.selected');
  await expect(annotation).toHaveCount(1);
  const expected = await page.request.get(`/api/v1/projects/${sourceId}/pages/${row!.source.page}`);
  const data = (await expected.json()) as {
    width: number;
    height: number;
    annotations: { compound_id: string; bbox: number[] }[];
  };
  const bbox = data.annotations.find((value) => value.compound_id === row!.id)!.bbox;
  const canvas = await page.locator('.page-canvas').boundingBox();
  const overlay = await annotation.boundingBox();
  expect(overlay!.width / canvas!.width).toBeCloseTo((bbox[2]! - bbox[0]!) / data.width, 2);
  expect(overlay!.height / canvas!.height).toBeCloseTo((bbox[3]! - bbox[1]!) / data.height, 2);
  await test.info().attach('source-layout', {
    body: JSON.stringify({
      projectId: sourceId,
      page: row!.source.page,
      before,
      after,
      canvas,
      overlay,
      bbox,
    }),
    contentType: 'application/json',
  });
});
