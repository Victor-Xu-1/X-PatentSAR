import { expect, test } from '@playwright/test';
import { decodeResults } from '../src/api/decoders';

// Generated original drawings, no model inference and no invented product IDs.
// Retention, selection and presentation evidence, not extraction accuracy.
for (const width of [390, 1672]) {
  test(`unproved drawings stay on the original and out of product tables at ${width}px`, async ({
    page,
  }) => {
    const project = process.env.PATENTSAR_E2E_CANDIDATE_PROJECT_ID;
    expect(project, 'Requires the isolated native candidate-observation fixture').toBeTruthy();
    const writes: string[] = [],
      errors: string[] = [],
      queries: string[] = [];
    page.on('pageerror', (error) => errors.push(error.message));
    await page.route('**/api/v1/**', async (route) => {
      if (route.request().method() !== 'GET') {
        writes.push(route.request().url());
        await route.abort();
      } else {
        const url = new URL(route.request().url());
        if (url.pathname.endsWith('/results')) queries.push(url.searchParams.get('q') ?? '');
        await route.continue();
      }
    });
    await page.setViewportSize({ width, height: width === 390 ? 844 : 1060 });
    await page.goto('/#/projects/' + project + '?page=1&tab=annotations&pdf=1');
    const rows = page.locator('.results-table tbody tr[data-compound]');
    // Wait for the normal UI session and source read, not a fixed delay or an
    // unauthenticated API request racing initial navigation.
    await expect(
      page.getByText('No confirmed numbered products yet', { exact: true }),
    ).toBeVisible();
    await expect(rows).toHaveCount(0);
    const endpoint = `/api/v1/projects/${project}/results`;
    const response = await page.request.get(endpoint);
    expect(response.ok(), await response.text()).toBeTruthy();
    const before = decodeResults(await response.json());
    expect(before.total).toBe(0);
    expect(before.items).toEqual([]);
    const original = page.locator('.page-canvas img');
    await expect(original).toBeVisible();
    await expect
      .poll(() => original.evaluate((image) => (image as HTMLImageElement).naturalWidth))
      .toBeGreaterThan(0);
    const annotation = page.locator('[data-annotation]');
    await expect(annotation).toHaveCount(1);
    const source = await annotation.getAttribute('data-annotation');
    expect(source).toMatch(/^source-structure:/);
    await expect(annotation).toHaveText('Unassigned drawing 1');
    await expect(page.getByText(/source-structure:/)).toHaveCount(0);
    await annotation.click();
    await expect(annotation).toHaveClass(/selected/);
    expect(queries).not.toContain(source);
    const rawSource = await page.request.get(
      `/api/v1/projects/${project}/structures/${encodeURIComponent(source!)}/image`,
    );
    expect(rawSource.ok()).toBeTruthy();
    const projectResponse = await page.request.get(`/api/v1/projects/${project}`);
    const capturedProject = await projectResponse.json();
    expect(capturedProject.summary.structures).toBe(2);
    expect(capturedProject.acceptance.state).not.toBe('accepted');
    await page
      .getByRole('combobox', { name: 'Interface language', exact: true })
      .selectOption('zh-CN');
    await expect(page.getByText('暂无已确认的编号终产物', { exact: true })).toBeVisible();
    await expect(annotation).toHaveText('未归属结构 1');
    await expect(rows).toHaveCount(0);
    await page.screenshot({ path: test.info().outputPath(`candidate-zh-${width}.png`) });
    await page.getByRole('combobox', { name: '界面语言', exact: true }).selectOption('en');
    await expect(
      page.getByText('No confirmed numbered products yet', { exact: true }),
    ).toBeVisible();
    expect(await page.evaluate(() => document.body.scrollWidth <= window.innerWidth + 1)).toBe(
      true,
    );
    await page.screenshot({ path: test.info().outputPath(`candidate-en-${width}.png`) });
    await page.reload();
    await expect(
      page.getByText('No confirmed numbered products yet', { exact: true }),
    ).toBeVisible();
    const after = decodeResults(await (await page.request.get(endpoint)).json());
    expect(after.items).toEqual(before.items);
    expect(writes).toEqual([]);
    expect(errors).toEqual([]);
  });
}
