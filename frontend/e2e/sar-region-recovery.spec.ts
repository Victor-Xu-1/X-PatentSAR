import { expect, test } from '@playwright/test';
import type { Locator, Page } from '@playwright/test';
import { syntheticSnapshot } from './sarSnapshotFixture';

async function guardRegionWrites(page: Page) {
  const forbidden: string[] = [];
  await page.route('**/api/v1/**', async (route) => {
    const request = route.request(),
      path = new URL(request.url()).pathname;
    if (
      request.method() !== 'GET' &&
      !(
        request.method() === 'POST' &&
        /^\/api\/v1\/sar\/datasets\/[a-f0-9]{32}\/regions$/.test(path)
      )
    ) {
      forbidden.push(path);
      await route.abort();
    } else await route.continue();
  });
  return forbidden;
}

async function selection(page: Page) {
  await page.getByText('Single-reference comparison (advanced)', { exact: true }).click();
  const rows = page.getByRole('region', { name: 'Choose reference molecule', exact: true });
  await rows.getByRole('button', { name: 'Reference', exact: true }).first().click();
  const panel = page.getByRole('region', { name: 'Select variable region', exact: true });
  const atom = panel.getByRole('button', { name: 'Atom 0 (C)', exact: true });
  await expect(atom).toBeEnabled();
  await atom.click();
  return panel;
}
async function recover(panel: Locator, page: Page) {
  await expect(
    panel.getByRole('button', { name: 'Check saved selection', exact: true }),
  ).toBeEnabled();
  await expect(panel.getByRole('button', { name: 'Save region', exact: true })).toBeDisabled();
  await page
    .getByRole('combobox', { name: 'Interface language', exact: true })
    .selectOption('zh-CN');
  const chinese = page.getByRole('region', { name: '选择变化区域', exact: true });
  await chinese.getByRole('button', { name: '检查已保存选区', exact: true }).click();
  await expect(chinese.getByText('区域已保存 · 1 个连接点', { exact: true })).toBeVisible();
  await expect(chinese.getByRole('button', { name: '保存区域', exact: true })).toBeDisabled();
  return chinese;
}

for (const width of [390, 1672]) {
  for (const interrupted of [false, true]) {
    test(`saved region readback without replay after ${interrupted ? 'leaving' : 'response loss'} at ${width}px`, async ({
      page,
    }, info) => {
      test.skip(process.env.PATENTSAR_E2E_SAR_MUTATIONS !== 'synthetic-isolated-state');
      await page.setViewportSize({ width, height: width === 390 ? 844 : 1060 });
      await page.emulateMedia({ reducedMotion: 'reduce' });
      const forbidden = await guardRegionWrites(page);
      const dataset = await syntheticSnapshot(page),
        profilePath = '/api/v1/sar/datasets/' + dataset.id + '/profile';
      const before = await (await page.request.get(profilePath)).json();
      const panel = await selection(page);
      let release!: () => void, committed!: () => void;
      const held = new Promise<void>((resolve) => {
        release = resolve;
      });
      const received = new Promise<void>((resolve) => {
        committed = resolve;
      });
      let posts = 0;
      await page.route('**/api/v1/sar/datasets/' + dataset.id + '/regions', async (route) => {
        posts++;
        const response = await route.fetch();
        expect(response.status()).toBe(201);
        committed();
        if (interrupted) {
          await held;
          await route.fulfill({ response });
        } else
          await route.fulfill({
            status: 503,
            contentType: 'application/json',
            body: JSON.stringify({
              error: {
                code: 'controlled_lost_response',
                message: 'Controlled committed response loss.',
              },
            }),
          });
      });
      await panel.getByRole('button', { name: 'Save region', exact: true }).click();
      await received;
      if (interrupted) {
        await page.getByRole('button', { name: 'Change reference', exact: true }).click();
        const delivered = page.waitForResponse(
          (response) =>
            response.request().method() === 'POST' &&
            new URL(response.url()).pathname.endsWith('/' + dataset.id + '/regions'),
        );
        release();
        expect((await delivered).status()).toBe(201);
        await page.getByRole('button', { name: 'Return to selection', exact: true }).click();
      }
      await expect(
        panel.getByText('Region saved · 1 attachment points', { exact: true }),
      ).toHaveCount(0);
      const chinese = await recover(panel, page);
      const after = await (await page.request.get(profilePath)).json();
      expect(after.regions).toHaveLength(before.regions.length + 1);
      expect(posts).toBe(1);
      expect(after.regions.at(-1)).toMatchObject({
        name: 'Region',
        kind: 'variable',
        atom_indices: [0],
        dataset_revision: dataset.revision,
      });
      expect(
        (await (await page.request.get('/api/v1/sar/datasets/' + dataset.id + '/jobs')).json())
          .items,
      ).toEqual([]);
      expect(forbidden).toEqual([]);
      await chinese.screenshot({
        path: info.outputPath('restored-region.png'),
        animations: 'disabled',
      });
    });
  }
}
test('a noncommitted save stays unconfirmed without an automatic or user-recovery POST', async ({
  page,
}) => {
  test.skip(process.env.PATENTSAR_E2E_SAR_MUTATIONS !== 'synthetic-isolated-state');
  const forbidden = await guardRegionWrites(page);
  const dataset = await syntheticSnapshot(page),
    panel = await selection(page);
  let posts = 0;
  await page.route('**/api/v1/sar/datasets/' + dataset.id + '/regions', async (route) => {
    posts++;
    await route.fulfill({
      status: 503,
      contentType: 'application/json',
      body: JSON.stringify({
        error: {
          code: 'controlled_before_commit',
          message: 'Controlled failure without forwarding the POST.',
        },
      }),
    });
  });
  await panel.getByRole('button', { name: 'Save region', exact: true }).click();
  const check = panel.getByRole('button', { name: 'Check saved selection', exact: true });
  await expect(check).toBeEnabled();
  await check.click();
  await expect(panel.getByRole('alert')).toContainText(
    'unique matching saved selection has not been confirmed',
  );
  await expect(check).toBeEnabled();
  await expect(panel.getByRole('button', { name: 'Clear selection', exact: true })).toBeDisabled();
  await expect(panel.getByRole('button', { name: 'Save region', exact: true })).toBeDisabled();
  expect(posts).toBe(1);
  expect(forbidden).toEqual([]);
  expect(
    (await (await page.request.get('/api/v1/sar/datasets/' + dataset.id + '/profile')).json())
      .regions,
  ).toEqual([]);
});
