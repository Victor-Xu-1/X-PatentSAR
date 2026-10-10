import { expect, test } from '@playwright/test';
import { decodeEnvironmentCatalog } from '../src/api/environmentDecoders';
import { environmentComponentAction } from '../src/model/environmentStatus';
import { canSetupEnvironmentPlan, environmentSetupComponents } from '../src/model/environmentSetup';

for (const width of [390, 800, 1672]) {
  for (const language of ['en', 'zh-CN'] as const) {
    test(`daily task navigation and secondary environment records ${width}px ${language}`, async ({
      page,
    }) => {
      const id = process.env.PATENTSAR_E2E_FAILED_JOB_ID;
      expect(
        id,
        'One controlled empty-PDF failure supplies a real task record, not scientific acceptance',
      ).toMatch(/^[a-f0-9]{32}$/);
      const writes: string[] = [],
        errors: string[] = [];
      await page.route('**/api/v1/**', (route) => {
        if (route.request().method() !== 'GET') {
          writes.push(new URL(route.request().url()).pathname);
          return route.abort();
        }
        return route.continue();
      });
      page.on('pageerror', (error) => errors.push(error.message));
      await page.setViewportSize({ width, height: 1060 });
      await page.goto('/#/jobs');
      if (language === 'zh-CN')
        await page
          .getByRole('combobox', { name: 'Interface language', exact: true })
          .selectOption(language);
      const zh = language === 'zh-CN';
      await expect(page.locator('.job-card').first()).toBeVisible();
      const job = await (await page.request.get('/api/v1/jobs/' + id)).json();
      const project = await (await page.request.get('/api/v1/projects/' + job.project_id)).json();
      const row = page
        .locator('.job-card')
        .filter({ has: page.getByRole('button', { name: project.title, exact: true }) });
      const open = row.getByRole('button', {
        name: zh ? '打开工作台' : 'Open workspace',
        exact: true,
      });
      await expect(open).toHaveClass('primary');
      const titleReadability = await row.locator('.job-file .link-button').evaluate((title) => {
        const lineHeight = Number.parseFloat(getComputedStyle(title).lineHeight);
        return title.getBoundingClientRect().height <= lineHeight * 3 + 1;
      });
      expect(
        titleReadability,
        'A short original title must not become a vertical character column',
      ).toBe(true);
      await expect(
        row.getByRole('button', { name: zh ? '运行提取' : 'Run extraction', exact: true }),
      ).not.toHaveClass('primary');
      expect(
        await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth + 1),
      ).toBe(true);
      await page.screenshot({ path: test.info().outputPath('tasks.png') });
      await open.click();
      await expect(page).toHaveURL(new RegExp('#/projects/' + job.project_id));
      await expect(
        page.getByRole('button', { name: zh ? '环境管理' : 'Environment', exact: true }),
      ).toBeVisible();
      await page
        .getByRole('button', { name: zh ? '环境管理' : 'Environment', exact: true })
        .click();
      const catalog = decodeEnvironmentCatalog(
        await (await page.request.get('/api/v1/environments')).json(),
      );
      await expect(
        page.getByRole('heading', {
          name: zh ? '完整运行环境' : 'Complete runtime environment',
          exact: true,
        }),
      ).toBeVisible();
      await expect(
        page.getByRole('button', { name: zh ? '操作记录' : 'Operation records', exact: true }),
      ).toHaveCount(0);
      const plan = environmentSetupComponents(catalog);
      const preferredCheck =
        !canSetupEnvironmentPlan(plan) ||
        plan.some((component) => environmentComponentAction(component) === 'inspect');
      if (preferredCheck)
        await expect(
          page.getByRole('button', {
            name: zh ? /^(重新检测|检测全部组件)$/ : /^(Recheck|Check all components)$/,
          }),
        ).toHaveClass('primary');
      await page.screenshot({ path: test.info().outputPath('environment.png') });
      const details = page.getByRole('button', {
        name: zh ? '环境详情' : 'Environment details',
        exact: true,
      });
      await details.click();
      const parent = page.getByRole('dialog', {
        name: zh ? '环境详情' : 'Environment details',
        exact: true,
      });
      const field = parent.getByLabel(zh ? '上传文件目录' : 'Upload directory', { exact: true });
      const original = await field.inputValue();
      const value = (await field.isEnabled()) ? original + '/unsaved-browser-draft' : original;
      if (await field.isEnabled()) await field.fill(value);
      const records = parent.getByRole('button', {
        name: zh ? '操作记录' : 'Operation records',
        exact: true,
      });
      await records.click();
      const history = page.getByRole('dialog', {
        name: zh ? '环境操作记录' : 'Environment operation records',
        exact: true,
      });
      await expect(history).toBeVisible();
      await expect(history.locator('.feedback.loading')).toHaveCount(0);
      await page.screenshot({ path: test.info().outputPath('records.png') });
      await page.keyboard.press('Escape');
      await expect(history).toHaveCount(0);
      await expect(records).toBeFocused();
      await expect(field).toHaveValue(value);
      await parent.getByRole('button', { name: zh ? '取消' : 'Cancel', exact: true }).click();
      await expect(details).toBeFocused();
      expect(
        await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth + 1),
      ).toBe(true);
      expect(writes).toEqual([]);
      expect(errors).toEqual([]);
    });
  }
}
