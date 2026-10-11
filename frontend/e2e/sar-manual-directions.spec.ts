import { expect, test, type Page } from '@playwright/test';
import { createNetwork } from './sar-network-actions';

async function drawingsReady(page: Page) {
  await page.waitForFunction(() =>
    [...document.querySelectorAll('img')]
      .filter((element) => element.checkVisibility())
      .every(
        (element) =>
          (element as HTMLImageElement).complete && (element as HTMLImageElement).naturalWidth > 0,
      ),
  );
}

for (const width of [390, 800, 1672]) {
  test(`manual directions share the core workbench and exact measured preview at ${width}`, async ({
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
    const { job, dataset, report } = await createNetwork(page, width, undefined, true);
    const raw = await (
      await page.request.get(`/api/v1/sar/jobs/${job}/study/export?format=json`)
    ).text();
    const overview = await (await page.request.get(`/api/v1/sar/jobs/${job}/study`)).json();
    expect(overview.report.discovery).toBeNull();
    expect(overview.report.regions).toHaveLength(2);
    expect(
      overview.report.regions.every((item: { origin: string }) => item.origin === 'manual'),
    ).toBe(true);
    const requests: string[] = [];
    page.on('request', (request) => {
      if (request.url().includes('/study/rows?')) requests.push(request.url());
    });
    await report.getByRole('button', { name: 'Variable regions', exact: true }).click();
    const network = report.getByRole('region', { name: 'Single-site comparisons', exact: true });
    await expect(
      network.getByRole('button', { name: 'All directions', exact: true }),
    ).toHaveAttribute('aria-pressed', 'true');
    for (const label of ['2', '3', '4'])
      await expect(
        network.getByRole('button', { name: 'Compare ' + label, exact: true }),
      ).toBeVisible();
    await expect(network.locator('.sar-network-branch')).toHaveCount(3);
    const halogenBranch = network
      .locator('.sar-network-branch')
      .filter({ has: page.getByRole('button', { name: 'Compare 3', exact: true }) });
    await expect(halogenBranch.locator('.sar-branch-site-label')).toHaveText('R2');
    expect(requests).toHaveLength(1);
    const noActivity = network
      .locator('.sar-network-branch')
      .filter({ has: page.getByRole('button', { name: 'Compare 4', exact: true }) });
    await expect(noActivity.locator('.sar-branch-measurement dd').first()).toHaveText('—');
    await expect(noActivity.locator('.sar-branch-measurement dd').last()).toHaveText('4');
    await drawingsReady(page);
    await network.screenshot({ path: test.info().outputPath(`manual-directions-${width}.png`) });
    const legend = network.locator('.sar-region-legend');
    await legend.getByRole('button', { name: 'Halogen 原文', exact: true }).click();
    await expect(network.locator('.sar-network-branch')).toHaveCount(1);
    await expect(network.getByRole('button', { name: 'Compare 3', exact: true })).toBeVisible();
    await expect(halogenBranch.locator('.sar-branch-site-label')).toHaveText('R2');
    await network.getByRole('button', { name: 'All directions', exact: true }).click();
    await expect(network.locator('.sar-network-branch')).toHaveCount(3);
    await network.getByRole('button', { name: 'Compare 2', exact: true }).click();
    const preview = network.getByRole('region', { name: 'Transformation preview', exact: true });
    await expect(
      preview.getByRole('table', { name: 'Recorded values', exact: true }),
    ).toBeVisible();
    await expect(
      preview.getByRole('row').filter({ hasText: 'IC50' }).locator('td').last(),
    ).toContainText('-9.00');
    await expect(
      preview.getByRole('row').filter({ hasText: 't_half' }).locator('td').last(),
    ).toContainText('1.00');
    await expect(preview.locator('.sar-molecule-comparison img')).toHaveCount(2);
    await drawingsReady(page);
    await preview.screenshot({ path: test.info().outputPath(`manual-comparison-${width}.png`) });
    await preview
      .getByRole('button', { name: 'Close transformation preview', exact: true })
      .click();
    await expect(network.getByRole('button', { name: 'Compare 2', exact: true })).toBeFocused();
    await network.getByRole('button', { name: 'View molecules', exact: true }).click();
    const table = report.getByRole('region', { name: 'Activity table', exact: true });
    await expect(table.getByRole('rowheader', { name: '4', exact: true })).toBeVisible();
    await expect(table.getByRole('rowheader', { name: '1', exact: true })).toHaveCount(0);
    await table.getByRole('button', { name: 'Filters and sort', exact: true }).click();
    await expect(table.getByRole('combobox', { name: 'Row scope', exact: true })).toHaveValue(
      'changes',
    );
    const core = overview.report.regions[0].region.molecule_id;
    await expect(
      table.getByRole('combobox', { name: 'Choose reference molecule', exact: true }),
    ).toHaveValue(core);
    await table.getByRole('button', { name: 'Reset filters and sort', exact: true }).click();
    await expect(table.getByRole('rowheader', { name: '1', exact: true })).toBeVisible();
    await page
      .getByRole('combobox', { name: 'Interface language', exact: true })
      .selectOption('zh-CN');
    const translated = page.getByRole('region', { name: '研究报告', exact: true });
    await translated.getByRole('button', { name: '变化区域', exact: true }).click();
    await expect(translated.getByRole('button', { name: '选择核心 1', exact: true })).toBeVisible();
    await expect(
      translated.getByRole('button', { name: '全部改造方向', exact: true }),
    ).toHaveAttribute('aria-pressed', 'true');
    await expect(translated.getByRole('button', { name: '比较 4', exact: true })).toBeVisible();
    await drawingsReady(page);
    await translated
      .getByRole('region', { name: '单点结构对比', exact: true })
      .screenshot({ path: test.info().outputPath(`manual-chinese-${width}.png`) });
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth + 1)).toBe(
      true,
    );
    expect(
      await (await page.request.get(`/api/v1/sar/jobs/${job}/study/export?format=json`)).text(),
    ).toBe(raw);
    expect((await page.request.get(`/api/v1/sar/datasets/${dataset}`)).status()).toBe(200);
    expect(errors).toEqual([]);
    expect(foreignWrites).toEqual([]);
  });
}
