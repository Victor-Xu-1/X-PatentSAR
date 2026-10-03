import { expect, test } from '@playwright/test';
import type { Compound } from '../src/api/types';
import { decodeJob, decodeProject, decodeResults } from '../src/api/decoders';
import { stageLabels } from '../src/model/presentation';
import { activityColumnContext, activityColumnLabel } from '../src/model/activityColumns';

const projectId =
  process.env.PATENTSAR_E2E_SOURCE_PROJECT_ID ?? process.env.PATENTSAR_E2E_HISTORY_PROJECT_ID;
const unavailableJobId = process.env.PATENTSAR_E2E_UNAVAILABLE_HISTORY_JOB_ID;
const progressJobId = process.env.PATENTSAR_E2E_PROGRESS_JOB_ID;

for (const viewport of [
  { width: 1672, height: 942 },
  { width: 1280, height: 800 },
  { width: 390, height: 844 },
]) {
  test(`real result density, columns and per-metric source at ${viewport.width}x${viewport.height}`, async ({
    page,
  }) => {
    test.skip(
      !projectId,
      'Requires an approved real results project; no API routes are mocked or seeded',
    );
    await page.setViewportSize(viewport);
    const errors: string[] = [];
    page.on('pageerror', (error) => errors.push(error.message));
    await page.goto(`/#/projects/${encodeURIComponent(projectId!)}`);
    await expect(page.locator('.shell-menu > summary[aria-label="更多"]')).toBeVisible();
    // The static shell appears before the real API session/data have finished loading.
    await expect(page.getByRole('table')).toBeVisible();
    const response = await page.request.get(
      `/api/v1/projects/${encodeURIComponent(projectId!)}/results?page=1&page_size=25`,
    );
    expect(response.ok()).toBe(true);
    const results = decodeResults(await response.json());
    const originalResponse = await page.request.get(
      `/api/v1/projects/${encodeURIComponent(projectId!)}`,
    );
    expect(
      decodeProject(await originalResponse.json()).pdf.available,
      'Activity source navigation requires the actual original PDF',
    ).toBe(true);
    expect(
      results.items.length,
      'Approved results must contain genuine measurements',
    ).toBeGreaterThan(0);
    const table = page.getByRole('table');
    await expect(table).toHaveAttribute('data-density', 'compact');
    await expect(page.getByLabel('项目真实统计')).toHaveCount(0);
    await expect(page.locator('.acceptance-banner')).toHaveCount(0);
    await expect(page.getByRole('button', { name: '列表选项' })).toBeVisible();
    const row = results.items.find((item) =>
      item.activities.some((activity) => activity.page !== null),
    )!;
    expect(row, 'A real measurement provenance page is required').toBeTruthy();
    const rendered = page
      .locator('.results-table tbody tr')
      .filter({ has: page.getByLabel(`选择化合物 ${row.display_id}`, { exact: true }) });
    await expect(rendered).toBeVisible();
    await page.getByLabel(`选择化合物 ${row.display_id}`, { exact: true }).check();
    const compact = await rendered.boundingBox();
    if (
      row.activities.length <= 6 &&
      row.activities.every((item) => String(item.value).length <= 80)
    ) {
      expect(
        compact!.height,
        'A three-context result must not regress to a 247px row',
      ).toBeLessThanOrEqual(160);
    }
    await page.getByRole('button', { name: '列表选项' }).click();
    await page.getByText('显示选项', { exact: true }).click();
    await page.getByRole('button', { name: '舒适视图' }).click();
    await page.keyboard.press('Escape');
    await expect(table).toHaveAttribute('data-density', 'comfortable');
    const comfortable = await rendered.boundingBox();
    expect(comfortable!.height).toBeGreaterThan(compact!.height);
    await page.getByRole('button', { name: '列表选项' }).click();
    await page.getByText('显示选项', { exact: true }).click();
    await page.getByRole('button', { name: '紧凑视图' }).click();
    await page.keyboard.press('Escape');
    await page.getByRole('button', { name: '显示列', exact: true }).click();
    const metric = results.metrics[0]!;
    expect(metric).toBeTruthy();
    for (const column of results.activity_columns!.filter((item) => item.name === metric)) {
      const label = [activityColumnLabel(column), activityColumnContext(column)]
        .filter(Boolean)
        .join(' · ');
      await page.getByLabel(`显示列 ${label}`, { exact: true }).uncheck();
      await expect(table.locator(`th[data-column="activity:${column.id}"]`)).toHaveCount(0);
      await expect(rendered.locator(`td[data-activity-column="${column.id}"]`)).toHaveCount(0);
    }
    await expect(page.getByLabel(`选择化合物 ${row.display_id}`, { exact: true })).toBeChecked();
    await page.getByRole('button', { name: '显示全部列' }).click();
    await page.keyboard.press('Escape');
    await expect(table.locator('th.activity-value-column').first()).toBeVisible();
    const measurement = row.activities.find((activity) => activity.page !== null)!;
    await rendered
      .getByRole('button', {
        name: `${row.display_id} ${measurement.name} 活性来源第 ${measurement.page} 页`,
        exact: true,
      })
      .first()
      .click();
    await expect(page.getByLabel('原始文档页码')).toHaveValue(String(measurement.page));
    await expect(page.getByRole('tab', { name: '原文视图' })).toHaveAttribute(
      'aria-selected',
      'true',
    );
    await expect(page).not.toHaveURL(/compound=/);
    const original = page.getByRole('img', {
      name: `原始专利 PDF 第 ${measurement.page} 页`,
      exact: true,
    });
    await expect(original).toBeVisible();
    await expect
      .poll(() => original.evaluate((element) => (element as HTMLImageElement).naturalWidth))
      .toBeGreaterThan(0);
    await expect(
      rendered
        .locator('button.activity-source')
        .filter({ hasText: String(measurement.value ?? '') })
        .first(),
    ).toBeVisible();
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth + 2)).toBe(
      true,
    );
    expect(errors).toEqual([]);
    await page.reload();
    await expect(page.getByLabel('原始文档页码')).toHaveValue(String(measurement.page));
    await expect(page.getByRole('table')).toHaveAttribute('data-density', 'compact');
    await test.info().attach('measured-result-density', {
      body: JSON.stringify({
        viewport,
        compact,
        comfortable,
        compound: row.id,
        metrics: results.metrics,
        source: measurement.page,
      }),
      contentType: 'application/json',
    });
  });
}

test('real source crop and RDKit redraw have separate provenance and images', async ({ page }) => {
  test.skip(!projectId, 'Requires an approved real results project');
  await page.goto(`/#/projects/${encodeURIComponent(projectId!)}`);
  await expect(page.getByRole('table')).toBeVisible();
  const response = await page.request.get(
    `/api/v1/projects/${encodeURIComponent(projectId!)}/results?page=1&page_size=25`,
  );
  const results = decodeResults(await response.json());
  const compound: Compound | undefined = results.items.find(
    (item) => item.structure_image_url && item.redraw_image_url && item.smiles,
  );
  expect(
    compound,
    'This gate requires an actual source crop and an RDKit-generated PNG from the additive API',
  ).toBeTruthy();
  await page.getByRole('button', { name: `查看 ${compound!.display_id} 结构详情` }).click();
  const comparison = page.getByLabel('原始裁图与 SMILES 重绘对照');
  const original = comparison.getByRole('img', {
    name: `${compound!.display_id} 的原始结构裁图`,
    exact: true,
  });
  const redraw = comparison.getByRole('img', {
    name: `${compound!.display_id} 的 SMILES 重绘（非原图）`,
    exact: true,
  });
  for (const image of [original, redraw]) {
    await expect(image).toBeVisible();
    await expect
      .poll(() => image.evaluate((element) => (element as HTMLImageElement).naturalWidth))
      .toBeGreaterThan(0);
  }
  expect(await redraw.getAttribute('src')).not.toBe(await original.getAttribute('src'));
  const left = await original.boundingBox();
  const right = await redraw.boundingBox();
  expect(left!.x + left!.width).toBeLessThanOrEqual(right!.x);
  await expect(page.getByLabel('当前 SMILES')).toHaveValue(compound!.smiles!);
  for (const url of [compound!.structure_image_url!, compound!.redraw_image_url!]) {
    const image = await page.request.get(url);
    expect(image.ok()).toBe(true);
    expect(image.headers()['content-type']).toMatch(/^image\/png/);
  }
  await expect(page.getByRole('dialog')).toContainText('不证明与原图一致');
  await page.getByText('原始提取证据 / 校验', { exact: true }).click();
  if (compound!.recognition?.token_confidence)
    await expect(page.getByRole('dialog')).toContainText('未校准');
});

test('real additive manual counts are not inferred from binding evidence', async ({ page }) => {
  test.skip(!projectId, 'Requires an approved real project on the integrated additive API');
  await page.goto(`/#/projects/${encodeURIComponent(projectId!)}`);
  await expect(page.getByRole('button', { name: '更多', exact: true })).toBeVisible();
  const response = await page.request.get(`/api/v1/projects/${encodeURIComponent(projectId!)}`);
  const project = decodeProject(await response.json());
  await page.getByRole('button', { name: '列表选项' }).click();
  await page.getByText('结果与验收详情', { exact: true }).click();
  for (const [label, value] of [
    ['绑定待核验', project.summary.needs_review],
    ['人工已复核', project.summary.manually_reviewed],
    ['人工待复核', project.summary.manual_review_pending],
  ] as const) {
    await expect(
      page.locator('.metric-card').filter({ has: page.getByText(label, { exact: true }) }),
    ).toContainText(value == null ? '未知' : String(value));
  }
});

test('a real shared-directory job never inherits a new successful stage history', async ({
  page,
}) => {
  test.skip(
    !unavailableJobId,
    'Requires an actual history-unavailable job, not an intercepted response',
  );
  await page.goto('/#/jobs');
  await expect(page.getByRole('button', { name: '更多', exact: true })).toBeVisible();
  const response = await page.request.get(`/api/v1/jobs/${encodeURIComponent(unavailableJobId!)}`);
  expect(response.ok()).toBe(true);
  const job = decodeJob(await response.json());
  expect(job.history_available).toBe(false);
  const card = page.locator('.job-card').filter({ hasText: job.id });
  await expect(card).toContainText('历史阶段不可用');
  await expect(card.locator('.stage.ok')).toHaveCount(0);
  await expect(card.locator('.stage-progress')).toHaveCount(0);
});

test('actual persisted stage progress, cache and resources use the existing job read path', async ({
  page,
}) => {
  test.skip(!progressJobId, 'Requires an ended real job with actual progress observations');
  await page.goto('/#/jobs');
  await expect(page.getByRole('button', { name: '更多', exact: true })).toBeVisible();
  const response = await page.request.get(`/api/v1/jobs/${encodeURIComponent(progressJobId!)}`);
  expect(response.ok()).toBe(true);
  const job = decodeJob(await response.json());
  expect(job.history_available).toBe(true);
  expect(['queued', 'running']).not.toContain(job.status);
  const stage = job.stages.find((item) => item.progress !== null);
  expect(
    stage,
    'A real observation is required; null progress cannot be promoted into a count',
  ).toBeTruthy();
  const progress = stage!.progress!;
  const card = page.locator('.job-card').filter({ hasText: job.id });
  const observed = card.locator('.stage').filter({ hasText: stageLabels[stage!.name] });
  await expect(observed.locator('.stage-progress')).toContainText(
    `${progress.completed} / ${progress.total}`,
  );
  await observed.locator('summary').click();
  await expect(observed).toContainText(
    `缓存命中 ${progress.cache_hits} · 失败 ${progress.failures}`,
  );
  await expect(observed).toContainText(
    progress.device === null ? '执行设备未知' : progress.device.toUpperCase(),
  );
  await expect(observed).toContainText(
    progress.peak_rss_mb === null ? '峰值 RSS 未提供' : `峰值 RSS ${progress.peak_rss_mb} MB`,
  );
  await expect(card.getByRole('progressbar')).toHaveCount(0);
});
