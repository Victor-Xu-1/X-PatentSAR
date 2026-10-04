import { readFile } from 'node:fs/promises';
import { expect, test } from '@playwright/test';
import { decodeJob, decodeJobs, decodeResults } from '../src/api/decoders';
import { METRIC_SPECS } from '../src/api/predictionTypes';

const projectId = process.env.PATENTSAR_E2E_COMPLETION_PROJECT_ID;
const execute = process.env.PATENTSAR_E2E_EXECUTE_COMPLETION === '1';
const originalSha = process.env.PATENTSAR_E2E_ORIGINAL_SHA256;
const existingJobId = process.env.PATENTSAR_E2E_COMPLETION_JOB_ID;

test('software completes existing unmeasured sources from the UI and persists SMILES and six properties', async ({
  page,
}) => {
  test.skip(
    !projectId || (!execute && !existingJobId) || !originalSha,
    'Requires a controller-approved isolated or current project and explicit task execution',
  );
  test.setTimeout(900_000);
  const errors: string[] = [];
  page.on('pageerror', (error) => errors.push(error.message));
  await page.goto(`/#/projects/${projectId}?tab=original`);
  await expect(page.getByRole('table')).toBeVisible();
  const project = await (await page.request.get(`/api/v1/projects/${projectId}`)).json();
  expect(project.pdf.sha256).toBe(originalSha);
  let job;
  if (existingJobId) {
    // Continue an already UI-submitted owned job, never submit a duplicate task.
    job = decodeJob(await (await page.request.get(`/api/v1/jobs/${existingJobId}`)).json());
  } else {
    const before = decodeJobs(
      await (await page.request.get(`/api/v1/jobs?project_id=${projectId}`)).json(),
    );
    const known = new Set(before.items.map((value) => value.id));
    await page.getByRole('button', { name: '列表选项', exact: true }).click();
    const action = page.getByRole('button', { name: '补齐结构与指标', exact: true });
    await expect(action).toBeEnabled();
    const submitted = page.waitForResponse(
      (response) =>
        response.request().method() === 'POST' &&
        response.url().endsWith(`/projects/${projectId}/jobs`),
    );
    await action.click();
    expect((await submitted).status()).toBe(202);
    // The UI may restore its hash before CDP can read a POST body. Read the
    // durable newly created identity and prove it wasn't an old cached task.
    const after = decodeJobs(
      await (await page.request.get(`/api/v1/jobs?project_id=${projectId}`)).json(),
    );
    const added = after.items.filter((value) => !known.has(value.id));
    expect(added).toHaveLength(1);
    job = added[0]!;
  }
  expect(job.project_id).toBe(projectId);
  expect(job.admet_only).toBe(true);
  expect(job.include_admet).toBe(true);
  const phases = new Set<string>();
  await expect
    .poll(
      async () => {
        const current = decodeJob(await (await page.request.get(`/api/v1/jobs/${job.id}`)).json());
        if (current.admet_stage?.progress?.phase) phases.add(current.admet_stage.progress.phase);
        if (['failed', 'cancelled', 'interrupted'].includes(current.status))
          throw new Error(`Completion ${current.status}: ${JSON.stringify(current.error)}`);
        return current.status;
      },
      { timeout: 840_000, intervals: [2000, 5000, 10000] },
    )
    .toBe('complete');
  await page.reload();
  await expect(page.getByRole('table')).toBeVisible();
  const observed = [];
  for (const label of ['Compound 8', 'Compound 428']) {
    const query = new URLSearchParams({
      column_filters: JSON.stringify([{ column: 'compound', op: 'eq', value: label }]),
    });
    const packet = decodeResults(
      await (await page.request.get(`/api/v1/projects/${projectId}/results?${query}`)).json(),
    );
    expect(packet.total).toBe(1);
    const source = packet.items[0]!;
    expect(source.activities).toEqual([]);
    expect(source.record_kind).toBe('structure_only');
    expect(source.recognition?.status).toBe('valid');
    expect(source.smiles).toBeTruthy();
    expect(source.admet?.status).toBe('complete');
    expect(source.admet?.properties.map((value) => value.key)).toEqual(
      METRIC_SPECS.map((value) => value.key),
    );
    expect(source.admet?.properties.every((value) => Number.isFinite(value.value))).toBe(true);
    observed.push(source);
    await page.goto(`/#/projects/${projectId}?${query}`);
    const rendered = page.locator(`tr[data-compound="${source.id}"]`);
    await expect(rendered).toBeVisible();
    for (const metric of METRIC_SPECS) {
      const cell = rendered.locator(`[data-property="${metric.key}"]`);
      await expect(cell).not.toHaveText('—');
    }
    await rendered.getByRole('button', { name: `查看 ${label} 结构详情`, exact: true }).click();
    await expect(page.getByRole('dialog').getByLabel('当前 SMILES')).toHaveValue(source.smiles!);
    const redraw = page.getByRole('img', {
      name: `${label} 的 SMILES 重绘（非原图）`,
      exact: true,
    });
    await expect
      .poll(() => redraw.evaluate((image) => (image as HTMLImageElement).naturalWidth))
      .toBeGreaterThan(0);
    await page.screenshot({
      path: test.info().outputPath(`${label.replace(' ', '-')}-complete.png`),
      fullPage: true,
    });
    await page.getByRole('button', { name: '关闭对话框', exact: true }).click();
    const correction = await (
      await page.request.get(
        `/api/v1/projects/${projectId}/structures/${encodeURIComponent(source.id)}/correction`,
      )
    ).json();
    expect(correction.values.smiles).toBe(source.smiles);
  }
  await page.getByRole('button', { name: '导出结果', exact: true }).click();
  const dialog = page.getByRole('dialog');
  await dialog.getByLabel('导出范围').selectOption('all');
  await dialog.getByLabel('文件格式').selectOption('json');
  const downloading = page.waitForEvent('download');
  await dialog.getByRole('button', { name: '生成并下载', exact: true }).click();
  const download = await downloading;
  const path = test.info().outputPath('completed-export.json');
  await download.saveAs(path);
  const exported = JSON.parse(await readFile(path, 'utf8'));
  expect(exported.review_only).toBe(true);
  for (const source of observed) {
    const value = exported.items.find((item: { id: string }) => item.id === source.id);
    expect(value.smiles).toBe(source.smiles);
    expect(value.activities).toEqual([]);
    expect(value.admet.properties).toEqual(source.admet!.properties);
  }
  await test.info().attach('completion-proof', {
    body: JSON.stringify(
      { projectId, jobId: job.id, phases: [...phases], sources: observed, errors },
      null,
      2,
    ),
    contentType: 'application/json',
  });
  expect(errors).toEqual([]);
});
