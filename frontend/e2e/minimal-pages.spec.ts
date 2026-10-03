import { expect, test } from '@playwright/test';
import { decodeProject, decodeResults } from '../src/api/decoders';

const projectId = process.env.PATENTSAR_E2E_SOURCE_PROJECT_ID;

for (const viewport of [
  { width: 1672, height: 942 },
  { width: 390, height: 844 },
]) {
  test(`neutral input, recent files and jobs at ${viewport.width}`, async ({ page }) => {
    await page.setViewportSize(viewport);
    const errors: string[] = [],
      writes: string[] = [];
    page.on('pageerror', (error) => errors.push(error.message));
    page.on('request', (request) => {
      if (request.url().includes('/api/v1/') && request.method() !== 'GET')
        writes.push(request.method());
    });
    const screens = [
      ['new-task', '上传专利 PDF', '01-input'],
      ['projects', '最近文件', '02-recent'],
      ['jobs', '任务记录', '03-jobs'],
    ] as const;
    for (const [route, heading, file] of screens) {
      await page.goto(`/#/${route}`);
      await expect(page.getByRole('heading', { name: heading, exact: true })).toBeVisible();
      await expect(page.locator('.loading-indicator')).toHaveCount(0);
      if (route === 'projects') await expect(page.locator('.recent-file').first()).toBeVisible();
      if (route === 'jobs') await expect(page.locator('.job-card').first()).toBeVisible();
      expect(
        await page.evaluate(() => getComputedStyle(document.documentElement).backgroundColor),
      ).toBe('rgb(255, 255, 255)');
      expect(
        await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth + 2),
      ).toBe(true);
      await page.screenshot({
        path: test.info().outputPath(`${file}-${viewport.width}.png`),
        fullPage: true,
      });
    }
    expect(writes).toEqual([]);
    expect(errors).toEqual([]);
  });
}

test('real unassociated structures remain visible with original crops and no invented activity', async ({
  page,
}) => {
  test.skip(!projectId, 'Requires an approved real source project');
  await page.goto(`/#/projects/${projectId}`);
  await expect(page.getByRole('table')).toBeVisible();
  const path = `/api/v1/projects/${projectId}`;
  const project = decodeProject(await (await page.request.get(path)).json());
  const all = decodeResults(await (await page.request.get(`${path}/results?page_size=25`)).json());
  const source = decodeResults(
    await (
      await page.request.get(`${path}/results?q=${encodeURIComponent('未关联结构')}&page_size=25`)
    ).json(),
  );
  expect(project.summary.structure_only).toBeGreaterThan(0);
  expect(source.total).toBe(project.summary.structure_only);
  expect(all.total).toBeGreaterThan(project.summary.confirmed);
  expect(
    source.items.every(
      (item) =>
        item.record_kind === 'structure_only' && !item.activities.length && item.smiles === null,
    ),
  ).toBe(true);
  await page.getByLabel('搜索结果').fill('未关联结构');
  await expect(page.locator('.results-table tbody tr').first()).toContainText('未关联活性');
  const image = page.locator('.results-table tbody img').first();
  await expect(image).toBeVisible();
  await expect
    .poll(() => image.evaluate((element) => (element as HTMLImageElement).naturalWidth))
    .toBeGreaterThan(0);
  await page.screenshot({
    path: test.info().outputPath('04-unassociated-sources.png'),
    fullPage: true,
  });
});
