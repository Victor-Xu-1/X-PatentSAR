import { expect, test } from '@playwright/test';
import packageMetadata from '../package.json' with { type: 'json' };
import { LOCALE_STORAGE_KEY } from '../src/i18n/locale';

// Existing Chinese navigation contracts remain explicit rather than setting product defaults.
test.beforeEach(async ({ page }) => {
  await page.addInitScript((key) => localStorage.setItem(key, 'zh-CN'), LOCALE_STORAGE_KEY);
});

const expectedVersion = packageMetadata.version;
const projectId = process.env.PATENTSAR_E2E_SOURCE_PROJECT_ID;
const primary = ['上传 PDF', '最近文件', '环境管理', '任务记录'];

// Shared responsive.css wraps brand/navigation below 900px; 560px adds a row.
function headerHeightBudget(width: number) {
  return width < 561 ? 165 : width < 900 ? 105 : 65;
}

for (const viewport of [
  { width: 1672, height: 942 },
  { width: 800, height: 900 },
  { width: 390, height: 844 },
]) {
  test(`direct topbar routes and PDF-only upload at ${viewport.width}`, async ({ page }) => {
    const errors: string[] = [],
      writes: string[] = [];
    page.on('pageerror', (error) => errors.push(error.message));
    page.on('request', (request) => {
      if (request.method() !== 'GET' && request.url().includes('/api/v1/'))
        writes.push(request.url());
    });
    await page.setViewportSize(viewport);
    await page.goto('/#/new-task');
    const header = page.locator('.topbar');
    const nav = header.getByRole('navigation', { name: '工作台导航' });
    for (const name of primary) {
      await expect(nav.getByRole('button', { name, exact: true })).toBeVisible();
      await expect(nav.getByRole('button', { name, exact: true }).locator('span')).toBeVisible();
    }
    await expect(header.locator('.topbar-version')).toHaveText(`v${expectedVersion}`);
    await expect(header.locator('details, .shell-menu')).toHaveCount(0);
    await expect(page.getByRole('heading', { name: '上传专利 PDF', exact: true })).toBeVisible();
    await expect(page.locator('.new-task-page input')).toHaveCount(1);
    await expect(page.locator('.task-advanced')).toHaveCount(0);
    await expect(page.getByText('高级选项', { exact: true })).toHaveCount(0);
    await expect(page.getByRole('button', { name: '开始提取', exact: true })).toBeDisabled();
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth + 2)).toBe(
      true,
    );
    const bounds = await header.boundingBox();
    expect(bounds!.height).toBeLessThan(headerHeightBudget(viewport.width));
    await page.screenshot({ path: test.info().outputPath('pdf-only-upload.png'), fullPage: true });
    for (const [name, hash, heading] of [
      ['环境管理', '#/settings', '环境管理'],
      ['任务记录', '#/jobs', '任务记录'],
      ['最近文件', '#/projects', '最近文件'],
      ['上传 PDF', '#/new-task', '上传专利 PDF'],
    ]) {
      await nav.getByRole('button', { name: name!, exact: true }).click();
      await expect(page).toHaveURL(new RegExp(hash! + '$'));
      await expect(page.getByRole('heading', { name: heading!, exact: true })).toBeVisible();
      if (name !== '上传 PDF')
        await expect(nav.getByRole('button', { name: name!, exact: true })).toHaveAttribute(
          'aria-current',
          'page',
        );
    }
    await page.reload();
    await expect(page.getByLabel('原始专利 PDF 文件')).toBeFocused();
    await expect(header.locator('.topbar-version')).toHaveText(`v${expectedVersion}`);
    expect(writes).toEqual([]);
    expect(errors).toEqual([]);
  });

  test(`all project shortcuts stay exposed at ${viewport.width}`, async ({ page }) => {
    test.skip(!projectId, 'Needs an approved existing project; read-only navigation only.');
    const writes: string[] = [];
    page.on('request', (request) => {
      if (request.method() !== 'GET' && request.url().includes('/api/v1/'))
        writes.push(request.url());
    });
    await page.setViewportSize(viewport);
    await page.goto('/#/projects/' + projectId);
    await expect(page.getByRole('table')).toBeVisible();
    const header = page.locator('.topbar');
    const nav = header.getByRole('navigation', { name: '工作台导航' });
    await expect(nav.getByRole('button')).toHaveCount(6);
    for (const name of [...primary, '返回结果表格', '证据摘要']) {
      await expect(nav.getByRole('button', { name, exact: true })).toBeVisible();
      await expect(nav.getByRole('button', { name, exact: true }).locator('span')).toBeVisible();
    }
    await expect(header.locator('.topbar-version')).toHaveText(`v${expectedVersion}`);
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth + 2)).toBe(
      true,
    );
    const bounds = await header.boundingBox();
    expect(bounds!.height).toBeLessThan(headerHeightBudget(viewport.width));
    await nav.getByRole('button', { name: '证据摘要', exact: true }).click();
    await expect(
      page
        .getByRole('region', { name: '同项目确定性证据摘要', exact: true })
        .getByRole('heading', { name: '证据摘要', exact: true }),
    ).toBeVisible();
    await nav.getByRole('button', { name: '返回结果表格', exact: true }).click();
    await expect(page.getByRole('table')).toBeVisible();
    await page.screenshot({
      path: test.info().outputPath('direct-workspace-topbar.png'),
      fullPage: true,
    });
    expect(writes).toEqual([]);
  });
}
