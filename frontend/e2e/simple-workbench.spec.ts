import { readFile } from 'node:fs/promises';
import { expect, test } from '@playwright/test';
import type { Page } from '@playwright/test';
import { decodeJob, decodeProject, decodeResults } from '../src/api/decoders';
import { decodeCorrection } from '../src/api/correctionDecoders';
import { METRIC_SPECS } from '../src/api/predictionTypes';

const projectId = process.env.PATENTSAR_E2E_SOURCE_PROJECT_ID;
const editAllowed = process.env.PATENTSAR_E2E_ALLOW_CORRECTION === 'isolated-state';
const path = () => `/api/v1/projects/${encodeURIComponent(projectId!)}`;
async function originalImage(page: Page, number: number) {
  const image = page.getByRole('img', { name: `原始专利 PDF 第 ${number} 页`, exact: true });
  await expect(image).toBeVisible();
  await expect
    .poll(() => image.evaluate((element) => (element as HTMLImageElement).naturalWidth))
    .toBeGreaterThan(0);
  return image;
}
for (const viewport of [
  { width: 1672, height: 942 },
  { width: 1280, height: 800 },
  { width: 390, height: 844 },
]) {
  test(`simple PDF/table defaults to the actual first structure page at ${viewport.width}`, async ({
    page,
  }) => {
    test.skip(!projectId, 'Requires an explicitly approved real project');
    await page.setViewportSize(viewport);
    const errors: string[] = [];
    page.on('pageerror', (error) => errors.push(error.message));
    await page.goto(`/#/projects/${projectId}`);
    await expect(page.getByRole('table')).toBeVisible();
    const project = decodeProject(await (await page.request.get(path())).json());
    expect(project.first_structure_page).toBeGreaterThan(1);
    const first = project.first_structure_page!;
    await expect(page.getByLabel('原始文档页码')).toHaveValue(String(first));
    await originalImage(page, first);
    await page.screenshot({
      path: test.info().outputPath(`default-structure-${viewport.width}.png`),
      fullPage: true,
    });
    await expect(page.locator('.primary-sidebar')).toHaveCount(0);
    const table = page.getByRole('table');
    const data = decodeResults(
      await (await page.request.get(`${path()}/results?page=1&page_size=25`)).json(),
    );
    await expect(table.getByRole('columnheader')).toHaveCount(
      11 + (data.activity_columns?.length ?? 0),
    );
    for (const spec of METRIC_SPECS)
      await expect(
        table.getByRole('columnheader', { name: spec.label, exact: true }),
      ).toBeVisible();
    await expect(page.getByRole('columnheader', { name: '绑定证据' })).toHaveCount(0);
    expect(data.items.length).toBeGreaterThan(0);
    const row = data.items[0]!;
    const activity = row.activities.find((item) => item.page !== null);
    if (activity) {
      await page
        .getByLabel(`${row.display_id} ${activity.name} 活性来源第 ${activity.page} 页`, {
          exact: true,
        })
        .first()
        .click();
      await expect(page.getByLabel('原始文档页码')).toHaveValue(String(activity.page));
      await originalImage(page, activity.page!);
      await page.reload();
      await expect(page.getByLabel('原始文档页码')).toHaveValue(String(activity.page));
      await originalImage(page, activity.page!);
    }
    await expect(table).toBeVisible();
    const crop = table.getByRole('img').first();
    await expect(crop).toBeVisible();
    await expect
      .poll(() => crop.evaluate((element) => (element as HTMLImageElement).naturalWidth))
      .toBeGreaterThan(0);
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth + 2)).toBe(
      true,
    );
    if (viewport.width >= 1101) {
      const workflow = await page.locator('.workflow-panel').boundingBox();
      const tableArea = await page.locator('.table-scroll').boundingBox();
      expect(workflow!.height).toBeLessThanOrEqual(40);
      expect(tableArea!.height).toBeGreaterThan(viewport.height * 0.65);
    }
    await page.screenshot({
      path: test.info().outputPath(`simple-${viewport.width}.png`),
      fullPage: true,
    });
    expect(errors).toEqual([]);
  });
}

test('explicit first page and draggable panes/columns retain user positioning', async ({
  page,
}) => {
  test.skip(!projectId, 'Requires an approved real project');
  await page.goto(`/#/projects/${projectId}?page=1&tab=original`);
  await expect(page.getByLabel('原始文档页码')).toHaveValue('1');
  await originalImage(page, 1);
  const divider = page.getByRole('slider', { name: '调整原文与结果宽度' });
  await divider.focus();
  await page.keyboard.press('ArrowRight');
  const width = await divider.getAttribute('aria-valuenow');
  await page.reload();
  await expect(divider).toHaveAttribute('aria-valuenow', width!);
  await expect(page.getByLabel('原始文档页码')).toHaveValue('1');
  const column = page.getByRole('slider', { name: '调整MW列宽' });
  await column.focus();
  await page.keyboard.press('ArrowRight');
  await expect(page.getByRole('table')).toHaveClass(/columns-resized/);
  await page.getByLabel('选择当前页全部化合物').check();
  await expect(page.getByLabel('选择当前页全部化合物')).toBeChecked();
});

test('online edits persist and trigger real owned ADMET without rerunning the PDF', async ({
  page,
}) => {
  test.skip(
    !projectId || !editAllowed,
    'Writes require an explicitly isolated copied state, never production',
  );
  test.setTimeout(240_000);
  await page.goto(`/#/projects/${projectId}`);
  await expect(page.getByRole('table')).toBeVisible();
  const before = decodeProject(await (await page.request.get(path())).json());
  const result = decodeResults(
    await (await page.request.get(`${path()}/results?page=1&page_size=25`)).json(),
  );
  const row = result.items[0]!;
  const correctionPath = `${path()}/structures/${encodeURIComponent(row.id)}/correction`;
  const basis = decodeCorrection(await (await page.request.get(correctionPath)).json());
  const savedName = `Isolation-edit-${Date.now()}`;
  await page.getByLabel(`修正 ${row.display_id}`, { exact: true }).click();
  await page.getByLabel('修正化合物编号').fill(savedName);
  // Controlled ethanol reference tests actual descriptor/model transport, not patent graph accuracy.
  await page.getByLabel('修正 SMILES', { exact: true }).fill('CCO');
  await page.getByLabel('测量 1 值', { exact: true }).fill('++');
  await page.getByLabel('测量 1 值类型', { exact: true }).selectOption('text');
  await page.screenshot({ path: test.info().outputPath('correction-dialog.png'), fullPage: true });
  const savedResponse = page.waitForResponse(
    (response) => response.url().endsWith('/correction') && response.request().method() === 'PUT',
  );
  await page.getByRole('button', { name: '保存修正', exact: true }).click();
  expect((await savedResponse).status()).toBe(200);
  await expect(page.getByRole('dialog')).toHaveCount(0);
  await page.reload();
  const saved = decodeCorrection(await (await page.request.get(correctionPath)).json());
  expect(saved.revision).toBe(basis.revision + 1);
  expect(saved.original).toEqual(basis.original);
  expect(saved.values.smiles).toBe('CCO');
  expect(saved.values.activities[0]?.value).toBe('++');
  expect(saved.values.display_id).toBe(savedName);
  let predicted = result.items[0]!;
  await expect
    .poll(
      async () => {
        const current = decodeResults(
          await (
            await page.request.get(
              `${path()}/results?q=${encodeURIComponent(savedName)}&page_size=25`,
            )
          ).json(),
        );
        predicted = current.items.find((item) => item.id === row.id)!;
        return predicted?.admet?.status;
      },
      { timeout: 205_000, intervals: [500, 1000, 2000] },
    )
    .toBe('complete');
  expect(predicted.admet!.properties).toHaveLength(6);
  expect(predicted.admet!.properties[0]!.value).toBeCloseTo(46.069, 2);
  const admetJob = decodeJob(
    await (await page.request.get(`/api/v1/jobs/${predicted.admet!.job_id}`)).json(),
  );
  expect(admetJob.admet_only).toBe(true);
  await expect
    .poll(
      async () =>
        decodeJob(await (await page.request.get(`/api/v1/jobs/${admetJob.id}`)).json()).status,
    )
    .toBe('complete');
  expect(admetJob.stages).toEqual([]);
  await page.getByLabel('搜索结果').fill(savedName);
  const displayed = page
    .locator('.results-table tbody tr')
    .filter({ has: page.getByLabel(`选择化合物 ${savedName}`, { exact: true }) });
  await expect(displayed).toContainText('46.07');
  await expect(displayed).toContainText('已修正');
  await page.screenshot({ path: test.info().outputPath('corrected-metrics.png'), fullPage: true });
  const after = decodeProject(await (await page.request.get(path())).json());
  expect(after.acceptance).toEqual(before.acceptance);
  expect(after.first_structure_page).toBe(before.first_structure_page);
  await page.getByLabel(`选择化合物 ${savedName}`, { exact: true }).check();
  await page.getByRole('button', { name: '导出所选 (1)', exact: true }).click();
  await page.getByLabel('文件格式').selectOption('json');
  const download = page.waitForEvent('download');
  await page.getByRole('button', { name: '生成并下载', exact: true }).click();
  const file = await download;
  const destination = test.info().outputPath('corrected-real-export.json');
  await file.saveAs(destination);
  const exported = JSON.parse(await readFile(destination, 'utf8')) as {
    review_only: boolean;
    items: typeof result.items;
  };
  expect(exported.review_only).toBe(true);
  expect(exported.items[0]?.display_id).toBe(savedName);
  expect(exported.items[0]?.admet?.properties).toHaveLength(6);
  await test.info().attach('actual-owned-prediction', {
    body: JSON.stringify({
      project: projectId,
      correction_revision: saved.revision,
      job: admetJob,
      result: predicted.admet,
    }),
    contentType: 'application/json',
  });
});
