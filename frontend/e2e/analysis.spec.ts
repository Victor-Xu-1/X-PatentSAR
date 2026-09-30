import { expect, test } from '@playwright/test';
import { decodeAdmet, decodeEvidenceSummary, decodeRecognition } from '../src/api/analysisDecoders';
import type { Project } from '../src/api/types';

const projectId = process.env.PATENTSAR_E2E_HISTORY_PROJECT_ID;
const runAnalysis = process.env.PATENTSAR_E2E_RUN_ANALYSIS === '1';
const cropId = process.env.PATENTSAR_E2E_ANALYSIS_COMPOUND_ID;

test('same-project deterministic summary uses real evidence and preserves formal acceptance', async ({
  page,
}) => {
  test.skip(!projectId, 'Requires an approved isolated result project');
  await page.goto(`/#/projects/${projectId}`);
  await expect(page.getByText(/^v\d/)).toBeVisible();
  const before = (await (
    await page.request.get(`/api/v1/projects/${projectId}`)
  ).json()) as Project;
  const response = page.waitForResponse((response) => response.url().endsWith('/evidence-summary'));
  await page.getByRole('tab', { name: '证据摘要' }).click();
  const received = await response;
  expect(received.ok(), 'The complete iteration requires the deterministic summary endpoint').toBe(
    true,
  );
  const stableResponse = await page.request.get(received.url());
  expect(stableResponse.ok(), 'Authenticated stable summary retrieval must also succeed').toBe(
    true,
  );
  expect(new URL(stableResponse.url()).pathname).toBe(
    `/api/v1/projects/${projectId}/evidence-summary`,
  );
  const summary = decodeEvidenceSummary(await stableResponse.json());
  expect(summary.project_id).toBe(projectId);
  expect(summary.acceptance).toEqual(before.acceptance);
  await expect(page.locator('.evidence-counts > div').filter({ hasText: '化合物' })).toContainText(
    String(summary.counts.compounds),
  );
  await expect(page.getByText(/不是 LLM 摘要/)).toBeVisible();
  for (const [label, count] of Object.entries({
    结构: summary.counts.structures,
    活性行: summary.counts.activity_rows,
    化合物: summary.counts.compounds,
    已有SMILES: summary.counts.smiles,
    来源已定位: summary.counts.source_located,
    待复核: summary.counts.needs_review,
  })) {
    await expect(
      page
        .locator('.evidence-counts > div')
        .filter({ has: page.getByText(label, { exact: true }) })
        .locator('dd'),
    ).toHaveText(String(count));
  }
  const after = (await (await page.request.get(`/api/v1/projects/${projectId}`)).json()) as Project;
  expect(after.acceptance).toEqual(before.acceptance);
  expect(after.summary).toEqual(before.summary);
});

test('actual local batch ADMET accepts typed molecules and shows engine, units and review-only results', async ({
  page,
  request,
}) => {
  test.skip(!runAnalysis, 'Set PATENTSAR_E2E_RUN_ANALYSIS=1 for approved bounded CPU inference');
  test.setTimeout(215_000);
  await page.goto('/#/');
  await expect(page.getByText(/^v\d/)).toBeVisible();
  await page.getByRole('tab', { name: '分子分析 · ADMET' }).click();
  await page.getByLabel('SMILES（每行一个，最多 50 个）').fill('CCO\nCCN');
  const response = page.waitForResponse((response) => response.url().endsWith('/analysis/admet'), {
    timeout: 195_000,
  });
  await page.getByRole('button', { name: '运行本地 ADMET' }).click();
  const received = await response;
  expect(received.request().postDataJSON()).toEqual({ smiles: ['CCO', 'CCN'] });
  expect(
    received.ok(),
    'No placeholder or unavailable model can satisfy inference acceptance',
  ).toBe(true);
  // Chromium can evict a fetch inspector body even though the app has rendered
  // it. After an acknowledged 200, independently read the same content-addressed
  // prediction through the real API, without changing the browser's session.
  const session = await request.get('/api/v1/session');
  expect(session.ok()).toBe(true);
  const csrf = ((await session.json()) as { csrf_token: string }).csrf_token;
  const durable = await request.post(received.url(), {
    data: received.request().postDataJSON(),
    headers: { Origin: new URL(received.url()).origin, 'X-CSRF-Token': csrf },
    timeout: 195_000,
  });
  expect(durable.ok()).toBe(true);
  const result = decodeAdmet(await durable.json());
  expect(result.review_only).toBe(true);
  expect(result.predictions).toHaveLength(2);
  await expect(page.locator('.molecule-result')).toHaveCount(2);
  for (const prediction of result.predictions) expect(prediction.properties).toHaveLength(52);
  await expect(page.locator('.admet-results')).toContainText(result.engine.name);
  await expect(page.getByText(/不改变正式提取/)).toBeVisible();
});

test('approved real crop DECIMER recognition feeds analysis without altering extracted SMILES or QA', async ({
  page,
}) => {
  test.skip(
    !runAnalysis || !projectId || !cropId,
    'Requires approved CPU inference and a representative crop compound ID',
  );
  test.setTimeout(410_000);
  await page.goto(`/#/projects/${projectId}`);
  await expect(page.getByText(/^v\d/)).toBeVisible();
  await page.getByLabel('搜索结果', { exact: true }).fill(cropId!);
  const row = page
    .locator('.results-table tbody tr')
    .filter({ has: page.getByLabel(`选择化合物 ${cropId}`, { exact: true }) });
  await expect(row).toBeVisible();
  const before = (await (
    await page.request.get(
      `/api/v1/projects/${projectId}/results?q=${encodeURIComponent(cropId!)}&page_size=100`,
    )
  ).json()) as unknown;
  const projectBefore = (await (
    await page.request.get(`/api/v1/projects/${projectId}`)
  ).json()) as Project;
  await row.locator('.crop-button').click();
  await expect(page.getByRole('dialog').getByRole('img')).toBeVisible();
  const recognition = page.waitForResponse((response) => response.url().endsWith('/recognize'), {
    timeout: 195_000,
  });
  await page.getByRole('button', { name: '识别真实裁图（DECIMER + QC）' }).click();
  const recognizedResponse = await recognition;
  expect(recognizedResponse.ok()).toBe(true);
  const result = decodeRecognition(await recognizedResponse.json());
  expect(result.status, 'The approved representative crop must pass actual QC').toBe('recognized');
  expect(result.compound_id).toBe(cropId);
  expect(result.review_only).toBe(true);
  await expect(page.getByLabel('SMILES（每行一个，最多 50 个）')).toHaveValue(result.smiles!);
  const prediction = page.waitForResponse(
    (response) => response.url().endsWith('/analysis/admet'),
    { timeout: 195_000 },
  );
  await page.getByRole('button', { name: '运行本地 ADMET' }).click();
  const admetResponse = await prediction;
  expect(admetResponse.ok()).toBe(true);
  expect(decodeAdmet(await admetResponse.json()).review_only).toBe(true);
  const after = (await (
    await page.request.get(
      `/api/v1/projects/${projectId}/results?q=${encodeURIComponent(cropId!)}&page_size=100`,
    )
  ).json()) as unknown;
  const projectAfter = (await (
    await page.request.get(`/api/v1/projects/${projectId}`)
  ).json()) as Project;
  expect(after).toEqual(before);
  expect(projectAfter.acceptance).toEqual(projectBefore.acceptance);
  await page.getByLabel('关闭对话框').click();
  await expect(row.locator('.crop-button')).toBeFocused();
});
