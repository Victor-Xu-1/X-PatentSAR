import { expect, test } from '@playwright/test';
import packageMetadata from '../package.json' with { type: 'json' };
import { LOCALE_STORAGE_KEY } from '../src/i18n/locale';

// CI starts the owned service immediately before this selected scope.
// Wait for its bounded startup; the tests below still verify exact identity.
test.beforeAll(async ({ request }) => {
  await expect
    .poll(
      async () => {
        try {
          const response = await request.get('/api/v1/health', { timeout: 2000 });
          return response.ok() && (await response.json()).ready === true;
        } catch {
          return false;
        }
      },
      { timeout: 15000, message: 'Owned browser fixture must become ready' },
    )
    .toBe(true);
});

// Explicit Chinese regression variant; language-switch.spec covers fresh English defaults.
test.beforeEach(async ({ page }) => {
  await page.addInitScript((key) => localStorage.setItem(key, 'zh-CN'), LOCALE_STORAGE_KEY);
});

// Python CI verifies this derived npm version against the contracts.py authority.
const expectedVersion = packageMetadata.version;
const routes = [
  { path: 'new-task', heading: '上传专利 PDF' },
  { path: 'projects', heading: '历史文件' },
  { path: 'jobs', heading: '任务记录' },
  { path: 'settings', heading: '环境管理' },
];

test('generated unconfirmed labels switch language without rewriting wire identity', async ({
  page,
}) => {
  const source = process.env.PATENTSAR_E2E_SOURCE_PROJECT_ID;
  expect(source).toBeTruthy();
  const writes: string[] = [];
  const identifier = 'source-structure:' + 'a'.repeat(32);
  // Explicit UI-wire fixture only: no dataset, graph, model or accepted result
  // is written. The retained controlled source image is used solely for layout.
  await page.route('**/api/v1/**', async (route) => {
    const request = route.request();
    if (request.method() !== 'GET') {
      writes.push(new URL(request.url()).pathname);
      await route.abort();
      return;
    }
    if (new URL(request.url()).pathname !== `/api/v1/projects/${source}/results`) {
      await route.continue();
      return;
    }
    const response = await route.fetch();
    const data = await response.json();
    const row = data.items[0];
    expect(row).toBeTruthy();
    data.items = [
      {
        ...row,
        id: identifier,
        display_id: '编号待确认 S0007',
        identifier_label: null,
        structure_id: 'S0007',
        record_kind: 'structure_only',
        activities: [],
        activity_rank_values: [],
        activity_bands: [],
        activity_source_keys: [],
        lead: null,
        smiles: null,
        redraw_image_url: null,
        correction: null,
        flags: ['unassociated_structure', 'structure_number_unconfirmed'],
      },
    ];
    data.total = 1;
    await route.fulfill({ response, json: data });
  });
  await page.goto('/#/projects/' + source);
  await expect(
    page.getByRole('button', { name: '查看 编号待确认 S0007 结构详情', exact: true }),
  ).toBeVisible();
  await page.getByRole('combobox', { name: '界面语言', exact: true }).selectOption('en');
  const trigger = page.getByRole('button', {
    name: 'View Identifier unconfirmed S0007 structure details',
    exact: true,
  });
  await expect(trigger).toBeVisible();
  await expect(trigger).toHaveAttribute('data-focus-key', 'detail:' + identifier);
  await trigger.click();
  await expect(
    page.getByRole('dialog', {
      name: 'Structure details · Identifier unconfirmed S0007',
      exact: true,
    }),
  ).toBeVisible();
  await page.keyboard.press('Escape');
  await page
    .getByRole('combobox', { name: 'Interface language', exact: true })
    .selectOption('zh-CN');
  await expect(
    page.getByRole('button', { name: '查看 编号待确认 S0007 结构详情', exact: true }),
  ).toBeVisible();
  expect(writes).toEqual([]);
});

for (const viewport of [
  { width: 1672, height: 942 },
  { width: 800, height: 900 },
  { width: 390, height: 844 },
]) {
  for (const route of routes) {
    test(`build version matches health and Header on ${route.path} at ${viewport.width}`, async ({
      page,
    }) => {
      const writes: string[] = [];
      page.on('request', (request) => {
        if (request.method() !== 'GET' && new URL(request.url()).pathname.startsWith('/api/v1/'))
          writes.push(request.url());
      });
      await page.setViewportSize(viewport);
      // Observe the rendered page's real health fetch without retaining a CDP
      // body handle across navigation. Chromium can retire that handle even
      // while response.json() is already pending. Read persisted health using
      // the same isolated authenticated context, never replay a mutation.
      const healthResponse = page
        .waitForResponse(
          (response) =>
            response.request().method() === 'GET' &&
            new URL(response.url()).pathname === '/api/v1/health',
        )
        .then((response) => response.ok());
      await page.goto(`/#/${route.path}`);
      expect(await healthResponse).toBe(true);
      const current = await page.request.get('/api/v1/health');
      expect(current.ok()).toBe(true);
      const health = await current.json();
      expect(health.product.name).toBe('X-PatentSAR');
      expect(health.product.version).toBe(expectedVersion);
      await expect(page.getByRole('heading', { name: route.heading, exact: true })).toBeVisible();
      const version = page.locator('.topbar').getByLabel('软件版本', { exact: true });
      await expect(version).toBeVisible();
      await expect(version).toHaveText(`v${expectedVersion}`);
      expect(writes).toEqual([]);
    });
  }
}
