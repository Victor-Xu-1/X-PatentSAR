import { expect, test } from '@playwright/test';
import { decodeJob, decodeProject } from '../src/api/decoders';
import { decodeHistoryEntry } from '../src/api/historyDecoders';
import type { HistoryEntry } from '../src/api/historyTypes';
import {
  historyRow,
  ownedFailedProject,
  prepareHistory,
  readEntry,
  restoreFromTrash,
} from './history-fixture';

test.beforeEach(async ({ page }) => prepareHistory(page));

for (const width of [390, 800, 1672]) {
  test(`history read faults retain unknown counts and recover in both languages at ${width}px`, async ({
    page,
  }, info) => {
    await page.setViewportSize({ width, height: 1060 });
    const errors: string[] = [],
      writes: string[] = [];
    page.on('pageerror', (error) => errors.push(error.message));
    page.on('request', (request) => {
      if (request.method() !== 'GET' && new URL(request.url()).pathname.startsWith('/api/v1/'))
        writes.push(request.url());
    });
    for (const language of ['en', 'zh-CN']) {
      await page
        .getByRole('combobox', { name: /^(Interface language|界面语言)$/ })
        .selectOption(language);
      const english = language === 'en';
      const label = (en: string, zh: string) => (english ? en : zh);
      let release!: () => void;
      let pending = new Promise<void>((resolve) => {
        release = resolve;
      });
      await page.route('**/api/v1/history?**', async (route) => {
        if (route.request().method() !== 'GET') return route.continue();
        await pending;
        await route.fulfill({
          status: 503,
          contentType: 'application/json',
          body: JSON.stringify({
            error: {
              code: 'controlled_history_read_failure',
              message: 'Controlled read fault; no record count was returned.',
            },
          }),
        });
      });
      try {
        await page.getByRole('button', { name: label('Trash', '回收站'), exact: true }).click();
        const dialog = page.getByRole('dialog', { name: label('Trash', '回收站'), exact: true });
        const pagination = dialog.locator('.history-pagination');
        for (const kind of ['project', 'job', 'export', 'environment_operation']) {
          if (kind !== 'project') {
            pending = new Promise<void>((resolve) => {
              release = resolve;
            });
            await dialog
              .getByRole('combobox', { name: label('Trash record type', '回收站记录类型') })
              .selectOption(kind);
          }
          await expect(
            dialog.getByText(label('Loading records…', '正在读取记录…'), { exact: true }),
          ).toBeVisible();
          await expect(pagination).toHaveText(new RegExp(label('Page 1', '第 1 页')));
          await expect(pagination).not.toContainText(label('Records:', '共 '));
          await expect(
            dialog.getByRole('button', { name: label('Refresh records', '刷新记录'), exact: true }),
          ).toBeDisabled();
          if (kind === 'project')
            await page.screenshot({
              path: info.outputPath(`history-loading-${language}-${width}.png`),
            });
          release();
          await expect(dialog.getByRole('alert')).toBeVisible();
          await expect(pagination).not.toContainText(label('Records:', '共 '));
          await expect(
            dialog.getByText(label('No records of this type in Trash.', '此类型回收站为空。'), {
              exact: true,
            }),
          ).toHaveCount(0);
          await expect(
            dialog.getByRole('button', { name: label('Next history page', '下一页历史记录') }),
          ).toBeDisabled();
        }
        await page.screenshot({
          path: info.outputPath(`history-read-error-${language}-${width}.png`),
        });
        expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(
          width,
        );
        await page.unroute('**/api/v1/history?**');
        // Only a successful native read can publish an actual population, including zero.
        await dialog
          .getByRole('button', { name: label('Reload', '重新加载'), exact: true })
          .click();
        await expect(dialog.getByRole('alert')).toHaveCount(0);
        await expect(pagination).toContainText(label('Records:', '共 '));
        await page.keyboard.press('Escape');
        await expect(
          page.getByRole('button', { name: label('Trash', '回收站'), exact: true }),
        ).toBeFocused();
      } finally {
        release();
        await page.unroute('**/api/v1/history?**');
      }
    }
    expect(errors).toEqual([]);
    expect(writes).toEqual([]);
  });
}

for (const language of ['en', 'zh-CN']) {
  test(`committed history deletion with a lost response requires readback, never replay, in ${language}`, async ({
    page,
  }, info) => {
    await page.setViewportSize({ width: language === 'en' ? 390 : 1280, height: 1060 });
    await page.getByRole('combobox', { name: '界面语言', exact: true }).selectOption(language);
    const english = language === 'en';
    const label = (en: string, zh: string) => (english ? en : zh);
    const { job, project } = await ownedFailedProject(page);
    const entry = await readEntry(page, 'job', job.id);
    const ownerBefore = decodeProject(
      await (await page.request.get(`/api/v1/projects/${project.id}`)).json(),
    );
    const path = `/api/v1/history/job/${job.id}/delete`;
    const writes: string[] = [],
      errors: string[] = [];
    page.on('pageerror', (error) => errors.push(error.message));
    page.on('request', (request) => {
      if (
        request.method() === 'POST' &&
        new URL(request.url()).pathname.startsWith('/api/v1/history/')
      )
        writes.push(new URL(request.url()).pathname);
    });
    let committed: HistoryEntry | undefined;
    await page.route(`**${path}`, async (route) => {
      expect(route.request().method()).toBe('POST');
      expect(route.request().postDataJSON()).toEqual({ expected_revision: entry.revision });
      expect(route.request().headers()['x-csrf-token']).toBeTruthy();
      const returned = await route.fetch();
      expect(returned.ok()).toBe(true);
      committed = decodeHistoryEntry(await returned.json());
      expect(committed.deleted_at).not.toBeNull();
      // Actual mutation commits first; only its client response is replaced with a fault.
      await route.fulfill({
        status: 503,
        contentType: 'application/json',
        body: JSON.stringify({
          error: {
            code: 'controlled_lost_history_response',
            message: 'Controlled response loss after a committed history mutation.',
          },
        }),
      });
    });
    await page.goto('/#/jobs');
    await page.getByRole('button', { name: label('All records', '全部记录'), exact: true }).click();
    await historyRow(page, entry)
      .getByRole('button', { name: `${label('Delete', '删除')} ${entry.title}`, exact: true })
      .click();
    const modal = page.getByRole('dialog').last();
    const confirmButton = modal.getByRole('button', {
      name: label('Confirm move to Trash', '确认移入回收站'),
      exact: true,
    });
    await expect(confirmButton).toBeEnabled();
    await confirmButton.click();
    await expect(modal.getByRole('alert')).toBeVisible();
    await expect(confirmButton).toBeDisabled();
    expect(committed).toBeDefined();
    expect(writes).toEqual([path]);
    expect((await readEntry(page, 'job', job.id)).deleted_at).not.toBeNull();
    await page.screenshot({
      path: info.outputPath(`history-committed-response-lost-${language}.png`),
    });
    await page.unroute(`**${path}`);
    const refreshed = page.waitForResponse(
      (response) =>
        response.request().method() === 'GET' &&
        new URL(response.url()).pathname === `/api/v1/history/job/${job.id}`,
    );
    await modal
      .getByRole('button', { name: label('Refresh & review state', '刷新核对状态'), exact: true })
      .click();
    expect((await refreshed).ok()).toBe(true);
    await expect(modal).toHaveCount(0);
    await expect(historyRow(page, entry)).toHaveCount(0);
    await expect(
      page
        .getByRole('dialog')
        .getByRole('button', { name: label('Refresh records', '刷新记录'), exact: true }),
    ).toBeFocused();
    expect(writes).toEqual([path]);
    await page.keyboard.press('Escape');
    // Restore is a separate explicit user action against the new authoritative revision.
    await page
      .getByRole('combobox', { name: /^(Interface language|界面语言)$/ })
      .selectOption('zh-CN');
    await restoreFromTrash(page, await readEntry(page, 'job', job.id));
    expect(writes).toEqual([path, `/api/v1/history/job/${job.id}/restore`]);
    expect(decodeJob(await (await page.request.get(`/api/v1/jobs/${job.id}`)).json())).toEqual(job);
    expect(
      decodeProject(await (await page.request.get(`/api/v1/projects/${project.id}`)).json()),
    ).toEqual(ownerBefore);
    expect(errors).toEqual([]);
  });
}
