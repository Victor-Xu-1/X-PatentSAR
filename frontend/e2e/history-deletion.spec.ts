import { expect, test } from '@playwright/test';
import { decodeJob, decodeProject, decodeResults } from '../src/api/decoders';
import { decodeEnvironmentCatalog } from '../src/api/environmentDecoders';

import {
  baseURL,
  closeDialogs,
  confirm,
  environmentId,
  historyRow,
  openTrash,
  ownedFailedProject,
  prepareHistory,
  projectId,
  readEntry,
  readList,
  restoreFromTrash,
} from './history-fixture';

test('synthetic history controls and dialogs stay accessible at desktop and narrow widths', async ({
  page,
}, info) => {
  const errors: string[] = [];
  page.on('pageerror', (error) => errors.push(error.message));
  for (const viewport of [
    { width: 1280, height: 800 },
    { width: 390, height: 844 },
  ]) {
    await page.setViewportSize(viewport);
    await page.goto('/#/projects');
    const fileButton = page.getByRole('button', {
      name: '已生成文件 CI controlled historical adapter fixture (not extraction evidence)',
      exact: true,
    });
    await expect(fileButton).toBeVisible();
    expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(
      viewport.width,
    );
    await fileButton.click();
    const dialog = page.getByRole('dialog');
    await expect(dialog).toBeVisible();
    const bounds = await dialog.boundingBox();
    expect(bounds).not.toBeNull();
    expect(bounds!.x).toBeGreaterThanOrEqual(0);
    expect(bounds!.x + bounds!.width).toBeLessThanOrEqual(viewport.width);
    expect(bounds!.height).toBeLessThanOrEqual(viewport.height);
    await expect(dialog.getByRole('button', { name: '关闭', exact: true })).toBeVisible();
    for (let step = 0; step < 6; step++) {
      await page.keyboard.press('Tab');
      expect(await dialog.evaluate((element) => element.contains(document.activeElement))).toBe(
        true,
      );
    }
    await page.screenshot({
      path: info.outputPath(`history-dialog-${viewport.width}.png`),
      fullPage: true,
    });
    await page.keyboard.press('Escape');
    await expect(fileButton).toBeFocused();
    await page.goto('/#/jobs');
    await expect(page.getByRole('button', { name: '全部记录', exact: true })).toBeVisible();
    expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(
      viewport.width,
    );
    await page.screenshot({
      path: info.outputPath(`history-jobs-${viewport.width}.png`),
      fullPage: true,
    });
  }
  expect(errors).toEqual([]);
});

test.beforeEach(async ({ page }) => prepareHistory(page));

test('synthetic saved file deletes/restores through real API and survives navigation, retaining the table', async ({
  page,
}, info) => {
  const errors: string[] = [],
    writes: string[] = [];
  page.on('pageerror', (error) => errors.push(error.message));
  page.on('request', (request) => {
    if (request.method() === 'POST' && request.url().includes('/api/v1/history/'))
      writes.push(request.url());
  });
  const before = decodeResults(
    await (await page.request.get(`/api/v1/projects/${projectId}/results?page_size=100`)).json(),
  );
  expect(before.total).toBe(30);
  const files = await readList(page, 'export', false, projectId);
  expect(files.total).toBeLessThan(90); // Bounded synthetic fixture, never a production file inventory.
  const session = (await (await page.request.get('/api/v1/session')).json()) as {
    csrf_token: string;
  };
  const generated = await page.request.post(`/api/v1/projects/${projectId}/export`, {
    headers: { Origin: new URL(baseURL!).origin, 'X-CSRF-Token': session.csrf_token },
    data: { format: 'json', compound_ids: [] },
  });
  expect(generated.ok()).toBe(true);
  expect(generated.headers()['x-patentsar-content-sha256']).toMatch(/^[a-f0-9]{64}$/);
  const current = await readList(page, 'export', false, projectId);
  const created = current.items.filter((entry) => !files.items.some((old) => old.id === entry.id));
  expect(created).toHaveLength(1);
  const file = created[0]!;
  expect(file.project_id).toBe(projectId);
  await page
    .getByRole('button', {
      name: '已生成文件 CI controlled historical adapter fixture (not extraction evidence)',
      exact: true,
    })
    .click();
  const opener = historyRow(page, file).getByRole('button', {
    name: `删除 ${file.title}`,
    exact: true,
  });
  await opener.click();
  await expect(
    page.getByRole('dialog').last().getByRole('button', { name: '取消', exact: true }),
  ).toBeFocused();
  await page.keyboard.press('Escape');
  await expect(opener).toBeFocused();
  expect(writes).toHaveLength(0);
  await opener.click();
  await confirm(page, file);
  await expect(
    page.getByRole('dialog').getByRole('button', { name: '刷新记录', exact: true }),
  ).toBeFocused();
  await closeDialogs(page);
  await page.reload();
  expect(
    (await readList(page, 'export', false, projectId)).items.some((entry) => entry.id === file.id),
  ).toBe(false);
  await page.goto('/#/jobs');
  await restoreFromTrash(page, await readEntry(page, 'export', file.id));
  await page.reload();
  expect(
    (await readList(page, 'export', false, projectId)).items.some((entry) => entry.id === file.id),
  ).toBe(true);
  const after = decodeResults(
    await (await page.request.get(`/api/v1/projects/${projectId}/results?page_size=100`)).json(),
  );
  expect(after).toEqual(before);
  expect(writes).toHaveLength(2);
  expect(errors).toEqual([]);
  await page.screenshot({ path: info.outputPath('synthetic-file-restored.png'), fullPage: true });
});

test('synthetic job and project removal retains original facts and enforces parent-first recovery', async ({
  page,
}, info) => {
  const { job, project } = await ownedFailedProject(page);
  const entry = await readEntry(page, 'job', job.id);
  const owner = await readEntry(page, 'project', project.id);
  expect(entry.can_delete).toBe(true);
  expect(owner.can_delete).toBe(true);
  await page.goto('/#/jobs');
  await page.getByRole('button', { name: '全部记录', exact: true }).click();
  await historyRow(page, entry)
    .getByRole('button', { name: `删除 ${entry.title}`, exact: true })
    .click();
  await expect(
    page.getByRole('dialog').last().getByRole('button', { name: '确认移入回收站', exact: true }),
  ).toBeEnabled();
  await page.keyboard.press('Escape');
  await expect(
    historyRow(page, entry).getByRole('button', { name: `删除 ${entry.title}`, exact: true }),
  ).toBeFocused();
  await closeDialogs(page);
  const row = page
    .locator('.job-card')
    .filter({ has: page.getByText(`任务 ${job.id}`, { exact: true }) });
  await row.getByRole('button', { name: /^删除 / }).click();
  await expect(page.getByRole('dialog')).toContainText('当前表格、产物、生产记录和检查点文件不变');
  await confirm(page, entry);
  await closeDialogs(page);
  await expect(row).toHaveCount(0);
  await page.goto('/#/projects');
  await page.getByRole('button', { name: `删除 ${project.title}`, exact: true }).click();
  await expect(page.getByRole('dialog')).toContainText('PDF、结果和历史从日常视图');
  await confirm(page, await readEntry(page, 'project', project.id));
  await closeDialogs(page);
  await page.reload();
  await expect(
    page.getByRole('button', { name: `打开 ${project.title}`, exact: true }),
  ).toHaveCount(0);
  const child = await readEntry(page, 'job', job.id);
  expect(child.deleted_at).not.toBeNull();
  expect(child.can_restore).toBe(false);
  await openTrash(page, 'job');
  await historyRow(page, child)
    .getByRole('button', { name: `恢复 ${child.title}`, exact: true })
    .click();
  await expect(
    page.getByRole('dialog').last().getByRole('button', { name: '确认恢复' }),
  ).toBeDisabled();
  if (child.blocked_reason)
    await expect(page.getByRole('dialog').last()).toContainText(child.blocked_reason);
  await restoreFromTrash(page, await readEntry(page, 'project', project.id));
  const afterParent = await readEntry(page, 'job', job.id);
  expect(afterParent.deleted_at).not.toBeNull(); // Explicitly deleted record stays in trash until its own restore.
  expect(afterParent.can_restore).toBe(true);
  await restoreFromTrash(page, afterParent);
  const restored = decodeJob(await (await page.request.get(`/api/v1/jobs/${job.id}`)).json());
  expect(restored).toEqual(job);
  const restoredProject = decodeProject(
    await (await page.request.get(`/api/v1/projects/${project.id}`)).json(),
  );
  expect(restoredProject.pdf).toEqual(project.pdf);
  expect(restoredProject.summary).toEqual(project.summary);
  expect(restoredProject.acceptance).toEqual(project.acceptance);
  await page.reload();
  await expect(
    page.getByRole('button', { name: `打开 ${project.title}`, exact: true }),
  ).toBeVisible();
  await page.screenshot({
    path: info.outputPath('synthetic-project-restored.png'),
    fullPage: true,
  });
});

test('synthetic terminal environment history deletes/restores without installing or changing readiness', async ({
  page,
}, info) => {
  test.skip(
    !environmentId,
    'Requires an explicitly seeded terminal operation; never start models or installs to fill history.',
  );
  const entry = await readEntry(page, 'environment_operation', environmentId!);
  expect(entry.status).toBe('cancelled');
  expect(entry.can_delete).toBe(true);
  const catalog = decodeEnvironmentCatalog(
    await (await page.request.get('/api/v1/environments')).json(),
  );
  const before = { settings: catalog.settings, components: catalog.components };
  const mutations: string[] = [];
  page.on('request', (request) => {
    if (request.method() !== 'GET' && request.url().includes('/api/v1/'))
      mutations.push(new URL(request.url()).pathname);
  });
  await page.goto(`/#/settings?operation=${environmentId}`);
  await page.getByRole('button', { name: '环境详情', exact: true }).click();
  await page.getByRole('button', { name: '操作记录', exact: true }).click();
  await page
    .getByRole('dialog', { name: '环境操作记录', exact: true })
    .getByRole('button', { name: `删除 ${entry.title}`, exact: true })
    .click();
  await expect(page.getByRole('dialog').last()).toContainText('不卸载环境，也不改变环境就绪状态');
  await confirm(page, entry);
  await closeDialogs(page);
  await expect(page).not.toHaveURL(/operation=/);
  await page.reload();
  await page.getByRole('button', { name: '环境详情', exact: true }).click();
  await page.getByRole('button', { name: '操作记录', exact: true }).click();
  await expect(
    page
      .getByRole('dialog', { name: '环境操作记录', exact: true })
      .getByRole('button', { name: `删除 ${entry.title}`, exact: true }),
  ).toHaveCount(0);
  await page
    .getByRole('dialog', { name: '环境操作记录', exact: true })
    .getByRole('button', { name: '回收站', exact: true })
    .click();
  await page
    .getByRole('dialog', { name: '回收站', exact: true })
    .getByRole('button', { name: `恢复 ${entry.title}`, exact: true })
    .click();
  await confirm(page, await readEntry(page, 'environment_operation', environmentId!), true);
  await closeDialogs(page);
  const after = decodeEnvironmentCatalog(
    await (await page.request.get('/api/v1/environments')).json(),
  );
  expect({ settings: after.settings, components: after.components }).toEqual(before);
  expect(mutations).toEqual([
    `/api/v1/history/environment_operation/${environmentId}/delete`,
    `/api/v1/history/environment_operation/${environmentId}/restore`,
  ]);
  await page.screenshot({
    path: info.outputPath('synthetic-environment-restored.png'),
    fullPage: true,
  });
});
