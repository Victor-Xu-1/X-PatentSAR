import { expect, test } from '@playwright/test';
import { decodeResults } from '../src/api/decoders';

const projectId = process.env.PATENTSAR_E2E_CATALOG_PROJECT_ID;
test('real software-produced printed IDs retain unmeasured structures and reprint sources', async ({
  page,
}) => {
  test.skip(!projectId, 'Requires controller-approved current software catalog; read-only');
  await page.goto(`/#/projects/${projectId}`);
  await expect(page.getByRole('table')).toBeVisible();
  const endpoint = `/api/v1/projects/${projectId}/results`;
  for (const label of ['Compound 8', 'Compound 428']) {
    const criteria = [{ column: 'compound', op: 'eq', value: label }];
    const query = new URLSearchParams({ column_filters: JSON.stringify(criteria) });
    const packet = decodeResults(await (await page.request.get(`${endpoint}?${query}`)).json());
    expect(packet.total).toBe(1);
    const row = packet.items[0]!;
    expect(row.display_id).toBe(label);
    expect(row.record_kind).toBe('structure_only');
    expect(row.activities).toEqual([]);
    expect(row.structure_image_url).toBeTruthy();
    expect(row.smiles).toBeNull();
    await page.goto(`/#/projects/${projectId}?${query}`);
    const rendered = page
      .locator('tbody tr[data-compound]')
      .filter({ has: page.getByLabel(`选择化合物 ${label}`, { exact: true }) });
    await expect(rendered).toContainText('暂无活性数据');
    await expect(rendered).not.toContainText('编号待确认');
    await rendered.getByRole('button', { name: `查看 ${label} 结构详情`, exact: true }).click();
    const original = page.getByRole('img', { name: `${label} 的原始结构裁图`, exact: true });
    await expect(original).toBeVisible();
    await expect
      .poll(() => original.evaluate((image) => (image as HTMLImageElement).naturalWidth))
      .toBeGreaterThan(0);
    await page.getByRole('button', { name: '关闭对话框', exact: true }).click();
  }
  const criteria = [{ column: 'compound', op: 'eq', value: 'Compound 241' }];
  const query = new URLSearchParams({ column_filters: JSON.stringify(criteria) });
  const packet = decodeResults(await (await page.request.get(`${endpoint}?${query}`)).json());
  expect(packet.total).toBe(1);
  const row = packet.items[0]!;
  expect(row.additional_sources?.some((source) => source.page === 120)).toBe(true);
  await page.goto(`/#/projects/${projectId}?${query}`);
  await page.getByRole('button', { name: `查看 ${row.display_id} 结构详情`, exact: true }).click();
  await page
    .getByText(`同一编号的其他原文出处（${row.additional_sources!.length}）`, { exact: true })
    .click();
  await page.getByRole('link', { name: '原文第 120 页', exact: true }).click();
  await expect(page.getByLabel('原始文档页码', { exact: true })).toHaveValue('120');
  await expect(
    page.getByRole('img', { name: '原始专利 PDF 第 120 页', exact: true }),
  ).toBeVisible();
  await page.screenshot({
    path: test.info().outputPath('01-produced-id-catalog.png'),
    fullPage: true,
  });
});
