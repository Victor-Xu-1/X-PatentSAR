import { expect, test } from '@playwright/test';

for (const width of [390, 800, 1672]) {
  test(`software-owned indicator rules in both SAR entry points at ${width}px`, async ({
    page,
  }) => {
    test.skip(process.env.PATENTSAR_E2E_SAR_MUTATIONS !== 'synthetic-isolated-state');
    const errors: string[] = [],
      foreignWrites: string[] = [];
    page.on('pageerror', (error) => errors.push(error.message));
    await page.route('**/api/v1/**', async (route) => {
      const path = new URL(route.request().url()).pathname;
      if (route.request().method() !== 'GET' && !path.startsWith('/api/v1/sar/')) {
        foreignWrites.push(path);
        await route.abort();
      } else await route.continue();
    });
    await page.setViewportSize({ width, height: width === 390 ? 844 : 1060 });
    await page.goto('/#/sar');
    const imports = page.getByRole('region', { name: 'Import data', exact: true });
    await imports.getByRole('button', { name: 'CSV file', exact: true }).click();
    await imports.getByLabel('Choose a CSV file', { exact: true }).setInputFiles({
      name: `indicator-rules-${width}.csv`,
      mimeType: 'text/csv',
      buffer: Buffer.from(
        'id,smiles,IC50 (nM),pEC50,Ymin,Dmax (%),Ratio,assay\nI-1,COc1ccc(Cl)cc1,10,8,20,90,1,cell proliferation\nI-2,CCOc1ccc(Cl)cc1,1,9,10,95,2,cell proliferation\n',
      ),
    });
    await imports.getByRole('button', { name: 'Preview on server', exact: true }).click();
    await imports
      .getByRole('combobox', { name: 'Source identifier column', exact: true })
      .selectOption('id');
    await imports
      .getByRole('combobox', { name: 'SMILES column', exact: true })
      .selectOption('smiles');
    for (const name of ['IC50 (nM)', 'pEC50', 'Ymin', 'Dmax (%)', 'Ratio'])
      await imports.getByRole('checkbox', { name, exact: true }).check();
    await imports
      .getByRole('combobox', { name: 'Assay column (optional)', exact: true })
      .selectOption('assay');
    await imports.getByRole('button', { name: 'Create CSV dataset', exact: true }).click();
    await expect(page).toHaveURL(/dataset=[a-f0-9]{32}/);
    const datasetId = new URLSearchParams(new URL(page.url()).hash.split('?')[1]).get('dataset')!;
    const path = '/api/v1/sar/datasets/' + datasetId;
    const original = await (await page.request.get(path + '/molecules')).json();
    const profile = await (await page.request.get(path + '/profile')).json();
    expect(profile.contexts).toHaveLength(5);
    for (const item of profile.contexts) {
      const expected =
        item.name.includes('pEC50') || item.name.includes('Dmax')
          ? 'higher'
          : item.name === 'Ratio'
            ? 'unknown'
            : 'lower';
      expect(profile.policy_defaults[item.id].direction).toBe(expected);
    }
    expect((await (await page.request.get(path + '/jobs')).json()).items).toEqual([]);
    const setup = page.getByRole('region', { name: 'Study setup', exact: true });
    for (const name of [/IC50/, /pEC50/, /Ymin/, /Dmax/])
      await setup.getByRole('checkbox', { name }).check();
    await expect(
      setup.getByRole('status', { name: 'Activity direction', exact: true }),
    ).toHaveCount(4);
    await expect(
      setup.getByRole('combobox', { name: 'Activity direction', exact: true }),
    ).toHaveCount(0);
    await expect(setup.getByRole('button', { name: 'Continue', exact: true })).toBeEnabled();
    const policyGeometry = await setup.locator('.sar-policy .sar-form-grid').evaluateAll((rows) =>
      rows.map((row) => ({
        height: row.getBoundingClientRect().height,
        children: [...row.children].map((child) => ({
          tag: child.tagName,
          height: child.getBoundingClientRect().height,
          margin: getComputedStyle(child).margin,
        })),
      })),
    );
    console.log('automatic-policy-geometry', JSON.stringify({ width, policyGeometry }));
    expect(policyGeometry.every((row) => row.height <= 80)).toBe(true);
    await page.screenshot({
      path: test.info().outputPath(`known-rules-${width}.png`),
      fullPage: true,
    });
    await setup.getByRole('checkbox', { name: /Ratio/ }).check();
    await expect(setup.getByRole('button', { name: 'Continue', exact: true })).toBeDisabled();
    await setup
      .getByRole('combobox', { name: 'Activity direction', exact: true })
      .selectOption('higher');
    await expect(setup.getByRole('button', { name: 'Continue', exact: true })).toBeEnabled();
    await page.screenshot({
      path: test.info().outputPath(`unknown-confirmation-${width}.png`),
      fullPage: true,
    });
    const ic = profile.contexts.find((item: { name: string }) => item.name.includes('IC50'));
    const session = await page.request.get('/api/v1/session');
    const rejected = await page.request.post(path + '/studies', {
      headers: {
        Origin: new URL(page.url()).origin,
        'X-CSRF-Token': (await session.json()).csrf_token,
      },
      data: {
        request_id: 'f'.repeat(32),
        expected_dataset_revision: 1,
        title: 'Contradiction',
        policies: [{ context_id: ic.id, direction: 'higher' }],
      },
    });
    expect(rejected.status()).toBe(422);
    expect((await rejected.json()).error.code).toBe('sar_indicator_direction');
    await page.getByText('Single-reference comparison (advanced)', { exact: true }).click();
    const settings = page.getByRole('region', { name: 'Analysis settings', exact: true });
    await settings
      .getByRole('combobox', { name: 'Activity metric', exact: true })
      .selectOption(ic.metric_id);
    await expect(
      settings.getByRole('status', { name: 'Activity direction', exact: true }),
    ).toHaveText('Automatic · Lower is stronger');
    const pec = profile.contexts.find((item: { name: string }) => item.name.includes('pEC50'));
    await settings
      .getByRole('combobox', { name: 'Activity metric', exact: true })
      .selectOption(pec.metric_id);
    await expect(
      settings.getByRole('status', { name: 'Activity direction', exact: true }),
    ).toHaveText('Automatic · Higher is stronger');
    await page
      .getByRole('combobox', { name: 'Interface language', exact: true })
      .selectOption('zh-CN');
    await expect(
      page
        .getByRole('region', { name: '分析设置', exact: true })
        .getByRole('status', { name: '活性方向', exact: true }),
    ).toHaveText('自动 · 值越高活性越强');
    await page.screenshot({
      path: test.info().outputPath(`reference-rules-zh-${width}.png`),
      fullPage: true,
    });
    await page.getByRole('combobox', { name: '界面语言', exact: true }).selectOption('en');
    expect(await (await page.request.get(path + '/molecules')).json()).toEqual(original);
    expect((await (await page.request.get(path + '/jobs')).json()).items).toEqual([]);
    await setup.getByRole('button', { name: 'Continue', exact: true }).click();
    await setup.getByRole('checkbox', { name: 'Find single-site changes', exact: true }).uncheck();
    await setup.getByRole('button', { name: 'Run full study', exact: true }).click();
    await expect(page).toHaveURL(/job=[a-f0-9]{32}/);
    const job = new URLSearchParams(new URL(page.url()).hash.split('?')[1]).get('job');
    await expect(page.getByRole('navigation', { name: 'Study views', exact: true })).toBeVisible({
      timeout: 20000,
    });
    const packet = await (
      await page.request.get('/api/v1/sar/jobs/' + job + '/study/export?format=json')
    ).json();
    expect(packet.input.request.policies).toHaveLength(5);
    for (const policy of packet.input.request.policies) {
      const hint = profile.policy_defaults[policy.context_id];
      expect(policy.direction).toBe(hint.direction === 'unknown' ? 'higher' : hint.direction);
      expect(policy.grade_order).toEqual([]);
    }
    expect(packet.report.molecule_count).toBe(2);
    expect(errors).toEqual([]);
    expect(foreignWrites).toEqual([]);
  });
}
