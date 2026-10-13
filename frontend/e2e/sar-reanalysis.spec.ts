import { expect, test } from '@playwright/test';
import { createNetwork } from './sar-network-actions';

for (const width of [390, 800, 1672]) {
  test(`retained manual report starts a new full-library study only on confirmation at ${width}`, async ({
    page,
  }) => {
    test.skip(process.env.PATENTSAR_E2E_SAR_MUTATIONS !== 'synthetic-isolated-state');
    await page.setViewportSize({ width, height: 1060 });
    const errors: string[] = [],
      foreignWrites: string[] = [];
    page.on('pageerror', (error) => errors.push(error.message));
    await page.route('**/api/v1/**', (route) => {
      if (
        route.request().method() !== 'GET' &&
        !new URL(route.request().url()).pathname.startsWith('/api/v1/sar/')
      ) {
        foreignWrites.push(route.request().url());
        return route.abort();
      }
      return route.continue();
    });
    const { job, dataset, report } = await createNetwork(page, width, undefined, true, true);
    const original = await (
      await page.request.get(`/api/v1/sar/jobs/${job}/study/export?format=json`)
    ).text();
    await expect(report.getByText('Manual regions · 1 reference', { exact: true })).toBeVisible();
    const submissions: object[] = [];
    page.on('request', (request) => {
      if (
        request.method() === 'POST' &&
        new URL(request.url()).pathname === `/api/v1/sar/datasets/${dataset}/studies`
      )
        submissions.push(request.postDataJSON());
    });
    await report
      .locator('.sar-study-header')
      .screenshot({ path: test.info().outputPath(`manual-scope-${width}.png`) });
    await report.getByRole('button', { name: 'New analysis', exact: true }).click();
    const setup = page.getByRole('region', { name: 'Study setup', exact: true });
    await expect(setup.getByRole('button', { name: 'Run full study', exact: true })).toBeEnabled();
    await expect(setup.getByRole('heading', { name: 'Full SAR study', exact: true })).toBeFocused();
    await expect(
      setup.getByRole('checkbox', { name: 'Find single-site changes', exact: true }),
    ).toBeChecked();
    const title = `Full-library 原文 ${width}`;
    await setup.getByRole('textbox', { name: 'Study title', exact: true }).fill(title);
    await page
      .locator('summary')
      .filter({ hasText: /^Study setup$/ })
      .click();
    await page
      .getByRole('combobox', { name: 'Interface language', exact: true })
      .selectOption('zh-CN');
    await page.getByRole('button', { name: '继续设置', exact: true }).click();
    const translated = page.getByRole('region', { name: '研究设置', exact: true });
    await expect(translated.getByRole('textbox', { name: '研究名称', exact: true })).toHaveValue(
      title,
    );
    await translated.screenshot({ path: test.info().outputPath(`prefilled-chinese-${width}.png`) });
    expect(submissions).toEqual([]);
    await translated.getByRole('button', { name: '运行完整研究', exact: true }).click();
    await expect
      .poll(() => new URLSearchParams(new URL(page.url()).hash.split('?')[1]).get('job'))
      .not.toBe(job);
    const next = new URLSearchParams(new URL(page.url()).hash.split('?')[1]).get('job')!;
    expect(next).toMatch(/^[a-f0-9]{32}$/);
    const nextReport = page.getByRole('region', { name: '研究报告', exact: true });
    await expect(nextReport.getByRole('button', { name: '变化区域', exact: true })).toBeVisible({
      timeout: 20000,
    });
    expect(submissions).toHaveLength(1);
    expect(submissions[0]).toMatchObject({
      title,
      discover_single_sites: true,
      confirm_context: false,
      region_ids: [],
      core_ids: [],
    });
    const payload = submissions[0] as {
      policies: { strong_threshold: number | null; strength_method: string }[];
    };
    expect(payload.policies).toHaveLength(1);
    expect(payload.policies[0]).toMatchObject({
      strong_threshold: null,
      strength_method: 'tenth_decade',
    });
    const nextOverview = await (await page.request.get(`/api/v1/sar/jobs/${next}/study`)).json();
    expect(nextOverview.report.discovery).not.toBeNull();
    expect(
      new Set(
        nextOverview.report.regions.map(
          (item: { region: { molecule_id: string } }) => item.region.molecule_id,
        ),
      ).size,
    ).toBeGreaterThan(1);
    await expect(nextReport.locator('.sar-study-coverage')).toContainText('全库发现');
    await nextReport
      .locator('.sar-study-header')
      .screenshot({ path: test.info().outputPath(`automatic-scope-${width}.png`) });
    await page.reload();
    await expect(nextReport.getByRole('heading', { name: title, exact: true })).toBeVisible();
    expect(submissions).toHaveLength(1);
    expect(
      await (await page.request.get(`/api/v1/sar/jobs/${job}/study/export?format=json`)).text(),
    ).toBe(original);
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth + 1)).toBe(
      true,
    );
    expect(errors).toEqual([]);
    expect(foreignWrites).toEqual([]);
  });
}
