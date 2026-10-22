import { expect, test } from '@playwright/test';
import { createNetwork } from './sar-network-actions';

for (const width of [390, 800, 1672]) {
  test(`complete catalog and on-demand fragment details at ${width}`, async ({ page }) => {
    test.skip(process.env.PATENTSAR_E2E_SAR_MUTATIONS !== 'synthetic-isolated-state');
    await page.setViewportSize({ width, height: 1060 });
    const errors: string[] = [],
      reads: string[] = [],
      foreignWrites: string[] = [];
    page.on('pageerror', (error) => errors.push(error.message));
    page.on('request', (request) => {
      if (request.method() === 'GET') reads.push(new URL(request.url()).pathname);
    });
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
    const { job, report } = await createNetwork(page, width, undefined, true, true);
    const path = `/api/v1/sar/jobs/${job}/study`;
    expect(reads).toContain(path + '/catalog');
    expect(reads).not.toContain(path);
    expect(reads.some((value) => value.startsWith(path + '/regions/'))).toBe(false);
    const captured = await (await page.request.get(path + '/export?format=json')).text();
    const full = await (await page.request.get(path)).json();
    const catalog = await (await page.request.get(path + '/catalog')).json();
    expect(catalog.detail).toBe('catalog');
    expect(
      catalog.report.regions.map((item: { region: { id: string } }) => item.region.id),
    ).toEqual(full.report.regions.map((item: { region: { id: string } }) => item.region.id));
    expect(catalog.report.regions[0].fragments[0]).not.toHaveProperty('smiles');
    expect(catalog.report.regions[0].fragments[0]).not.toHaveProperty('bins');
    await report.getByRole('button', { name: 'Fragment summary', exact: true }).click();
    const fragments = report.getByRole('region', { name: 'Fragment summary', exact: true });
    await expect(fragments.getByRole('heading', { name: /Fragment 1/ })).toBeVisible();
    expect(reads).toContain(path + '/regions/' + full.report.regions[0].region.id);
    await fragments.getByRole('button', { name: 'Halogen 原文', exact: true }).click();
    await expect(fragments.getByRole('heading', { name: /Halogen 原文/ })).toBeVisible();
    expect(reads).toContain(path + '/regions/' + full.report.regions[1].region.id);
    await expect(fragments.getByRole('alert')).toHaveCount(0);
    await expect(fragments.locator('.sar-fragment-strip img')).toHaveCount(
      Math.min(6, full.report.regions[1].fragments.length),
    );
    await page.waitForFunction(() =>
      [...document.querySelectorAll('img')]
        .filter((image) => image.checkVisibility())
        .every(
          (image) =>
            (image as HTMLImageElement).complete && (image as HTMLImageElement).naturalWidth > 0,
        ),
    );
    await fragments.screenshot({ path: test.info().outputPath(`region-detail-${width}.png`) });
    await report.getByRole('button', { name: 'Variable regions', exact: true }).click();
    const network = report.getByRole('region', { name: 'Single-site comparisons', exact: true });
    await expect(
      network.getByRole('table', { name: 'Structure comparison', exact: true }),
    ).toBeVisible();
    await expect(network.getByRole('button', { name: 'Compare 2', exact: true })).toBeVisible();
    await network.getByRole('button', { name: 'Compare 2', exact: true }).click();
    const preview = network.getByRole('region', { name: 'Transformation preview', exact: true });
    await expect(
      preview.getByRole('table', { name: 'Recorded values', exact: true }),
    ).toBeVisible();
    await expect(preview.getByRole('alert')).toHaveCount(0);
    await preview
      .getByRole('button', { name: 'Close transformation preview', exact: true })
      .click();
    await page
      .getByRole('combobox', { name: 'Interface language', exact: true })
      .selectOption('zh-CN');
    const translated = page.getByRole('region', { name: '单点结构对比', exact: true });
    await expect(translated.getByRole('table', { name: '结构对照', exact: true })).toBeVisible();
    await page.waitForFunction(() =>
      [...document.querySelectorAll<HTMLImageElement>('.sar-network img')]
        .filter((image) => image.checkVisibility())
        .every((image) => image.complete && image.naturalWidth > 0),
    );
    await translated.screenshot({
      path: test.info().outputPath(`catalog-matrix-chinese-${width}.png`),
    });
    expect(await (await page.request.get(path + '/export?format=json')).text()).toBe(captured);
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth + 1)).toBe(
      true,
    );
    expect(errors).toEqual([]);
    expect(foreignWrites).toEqual([]);
  });
}

test('pooled full-network transport conserves every region and member without extra user choices', async ({
  page,
}) => {
  test.skip(process.env.PATENTSAR_E2E_SAR_MUTATIONS !== 'synthetic-isolated-state');
  const errors: string[] = [];
  page.on('pageerror', (error) => errors.push(error.message));
  const reads: string[] = [];
  page.on('request', (request) => {
    if (request.method() === 'GET')
      reads.push(new URL(request.url()).pathname + new URL(request.url()).search);
  });
  const csv =
    'id,smiles,IC50 (nM),t_half (h),target,assay,cell_line,duration\n' +
    Array.from(
      { length: 32 },
      (_, n) =>
        `${n + 1},${['COc1ccc(Cl)cc1', 'CCOc1ccc(Cl)cc1', 'COc1ccc(Br)cc1', 'CCCOc1ccc(Cl)cc1'][n % 4]},${n + 1},1,T,controlled,C,1h\n`,
    ).join('');
  const { job, report } = await createNetwork(page, 1672, csv, false, true);
  const path = `/api/v1/sar/jobs/${job}/study/catalog`;
  expect(reads).toContain(path + '?compact=true');
  // Navigation may release an earlier CDP response body; keep the real UI read
  // assertion, then compare two passive reads of this exact completed job.
  const response = await page.request.get(path + '?compact=true');
  expect(response.status()).toBe(200);
  const packed = await response.json();
  expect(packed.detail).toBe('catalog-pooled');
  expect(packed.wire_version).toBe(1);
  const legacyResponse = await page.request.get(path);
  expect(legacyResponse.status()).toBe(200);
  const legacy = await legacyResponse.json();
  const { wire_version: _version, fragment_pool, molecule_id_pool, ...body } = packed;
  const expanded = {
    ...body,
    detail: 'catalog',
    report: {
      ...body.report,
      regions: body.report.regions.map((region: { fragments: number[] }) => ({
        ...region,
        fragments: region.fragments.map((index) => ({
          ...fragment_pool[index],
          molecule_ids: molecule_id_pool[fragment_pool[index].molecule_ids],
        })),
      })),
    },
  };
  expect(expanded).toEqual(legacy);
  expect(Buffer.byteLength(JSON.stringify(packed))).toBeLessThan(
    Buffer.byteLength(JSON.stringify(legacy)),
  );
  await expect(report.getByRole('button', { name: 'Variable regions', exact: true })).toBeVisible();
  await page
    .getByRole('combobox', { name: 'Interface language', exact: true })
    .selectOption('zh-CN');
  await expect(
    page
      .getByRole('region', { name: '研究报告', exact: true })
      .getByRole('button', { name: '变化区域', exact: true }),
  ).toBeVisible();
  expect(errors).toEqual([]);
});
