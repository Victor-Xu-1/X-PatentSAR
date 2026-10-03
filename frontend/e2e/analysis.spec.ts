import { expect, test } from '@playwright/test';
import { decodeEvidenceSummary } from '../src/api/analysisDecoders';
import type { Project } from '../src/api/types';

const projectId = process.env.PATENTSAR_E2E_HISTORY_PROJECT_ID;
test('same-project deterministic summary uses real evidence and preserves formal acceptance', async ({
  page,
}) => {
  test.skip(!projectId, 'Requires an approved isolated result project');
  await page.goto(`/#/projects/${projectId}`);
  await expect(page.getByRole('button', { name: '更多', exact: true })).toBeVisible();
  const before = (await (
    await page.request.get(`/api/v1/projects/${projectId}`)
  ).json()) as Project;
  const response = page.waitForResponse((response) => response.url().endsWith('/evidence-summary'));
  await page.getByRole('button', { name: '更多', exact: true }).click();
  await page.getByRole('button', { name: /^证据摘要/ }).click();
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

test('opening source details does not start a competing model pipeline', async ({ page }) => {
  test.skip(!projectId, 'Requires an approved real result project');
  const modelRequests: string[] = [];
  page.on('request', (request) => {
    if (/\/analysis\/admet|\/recognize$/.test(request.url())) modelRequests.push(request.url());
  });
  await page.goto(`/#/projects/${projectId}`);
  const detail = page.getByRole('button', { name: /^查看 .+ 结构详情$/ }).first();
  await detail.click();
  await expect(page.getByRole('dialog')).toBeVisible();
  await expect(page.getByRole('button', { name: '运行本地 ADMET' })).toHaveCount(0);
  await expect(page.getByRole('button', { name: '识别真实裁图（DECIMER + QC）' })).toHaveCount(0);
  expect(modelRequests).toEqual([]);
});
