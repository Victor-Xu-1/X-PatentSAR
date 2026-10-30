import { expect, test } from '@playwright/test';

// Synthetic read failures only; never run extraction, a model or a production task.
for (const width of [390, 1672]) {
  test(`artifact failure remains explicit, bilingual and read-only at ${width}px`, async ({
    page,
  }, info) => {
    const origin = new URL(process.env.PATENTSAR_E2E_BASE_URL!);
    expect(['127.0.0.1', 'localhost', '[::1]']).toContain(origin.hostname);
    expect(Number(origin.port)).toBeGreaterThanOrEqual(18766);
    expect(Number(origin.port)).toBeLessThanOrEqual(18866);
    expect(process.env.PATENTSAR_E2E_RUN_JOBS).toBe('0');
    const project = process.env.PATENTSAR_E2E_SOURCE_PROJECT_ID!;
    const writes: string[] = [],
      errors: string[] = [];
    let fail = true,
      reads = 0;
    page.on('pageerror', (error) => errors.push(error.message));
    await page.route('**/api/v1/**', async (route) => {
      const request = route.request(),
        url = new URL(request.url());
      if (request.method() !== 'GET') {
        writes.push(url.pathname);
        return route.abort();
      }
      if (url.pathname === `/api/v1/projects/${project}/results`) {
        reads++;
        if (fail)
          return route.fulfill({
            status: 422,
            contentType: 'application/json',
            body: JSON.stringify({
              error: {
                code: 'invalid_artifact',
                message: 'Run artifact contains invalid JSON. CONTROLLED-DETAIL',
              },
            }),
          });
      }
      return route.continue();
    });
    await page.setViewportSize({ width, height: 1060 });
    await page.goto(`/#/projects/${project}`);
    const english = 'The task artifact is invalid; results are not available.';
    const chinese = '任务文件格式异常，结果尚不可用。';
    await expect(page.getByText(english, { exact: true })).toBeVisible();
    await expect(page.getByText('CONTROLLED-DETAIL', { exact: false })).toHaveCount(0);
    const before = reads;
    await page
      .getByRole('combobox', { name: 'Interface language', exact: true })
      .selectOption('zh-CN');
    await expect(page.getByText(chinese, { exact: true })).toBeVisible();
    expect(reads).toBe(before);
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth + 1)).toBe(
      true,
    );
    await page.screenshot({
      path: info.outputPath('01-artifact-error-zh.png'),
      animations: 'disabled',
    });
    fail = false;
    await page.getByRole('button', { name: '重新加载', exact: true }).click();
    await expect.poll(() => reads).toBeGreaterThan(before);
    await expect(page.getByText(chinese, { exact: true })).toHaveCount(0);
    await expect(page.getByRole('table')).toBeVisible();
    const original = page.getByRole('button', { name: '查看 Compound 1 结构详情', exact: true });
    await expect(original).toBeVisible();
    await expect(original).toHaveText('Compound 1');
    await page.getByRole('combobox', { name: '界面语言', exact: true }).selectOption('en');
    await expect(
      page.getByRole('button', { name: 'View Compound 1 structure details', exact: true }),
    ).toHaveText('Compound 1');
    await page.screenshot({
      path: info.outputPath('02-artifact-recovered-en.png'),
      animations: 'disabled',
    });
    expect(errors).toEqual([]);
    expect(writes).toEqual([]);
  });
}
