import { expect, test } from '@playwright/test';
import type { Page } from '@playwright/test';
import { decodeJob, decodeProject, decodeResults } from '../src/api/decoders';
import { decodeEnvironmentCatalog } from '../src/api/environmentDecoders';
import { decodeHistoryEntry, decodeHistoryList } from '../src/api/historyDecoders';
import type { HistoryEntry, HistoryKind } from '../src/api/historyTypes';

const projectId = process.env.PATENTSAR_E2E_HISTORY_PROJECT_ID;
const failedJobId = process.env.PATENTSAR_E2E_FAILED_JOB_ID;
const environmentId = process.env.PATENTSAR_E2E_ENVIRONMENT_OPERATION_ID;
const isolated = process.env.PATENTSAR_E2E_HISTORY_MUTATIONS === 'synthetic-isolated-state';
const baseURL = process.env.PATENTSAR_E2E_BASE_URL;
const output = process.env.PATENTSAR_E2E_OUTPUT_DIR;

// Only the controller's synthetic fixture is authorized. No copied patent,
// production lookup, success interception, service startup or model execution.
test.beforeEach(async ({ page }) => {
  test.skip(
    !isolated || !projectId || !failedJobId,
    'Requires explicit synthetic-isolated-state mutation consent and controlled fixture IDs.',
  );
  expect(
    baseURL,
    'Set the owned isolated backend explicitly; do not use the production default',
  ).toBeTruthy();
  const ciTemp = process.env.CI === 'true' ? process.env.RUNNER_TEMP : undefined;
  expect(output, 'Set an explicit external evidence directory').toBeTruthy();
  expect(
    Boolean(
      output && (/^\/srv\/wsl\//.test(output) || (ciTemp && output.startsWith(`${ciTemp}/`))),
    ),
    'Local evidence stays on E; CI evidence stays in its external runner temp',
  ).toBe(true);
  if (process.env.CI !== 'true')
    expect(
      new URL(baseURL!).port,
      'Only the controller-owned isolated port is authorized locally',
    ).toBe('18766');
  const session = await page.request.get('/api/v1/session');
  expect(session.ok(), 'Bootstrap the same-origin session before fixture API reads').toBe(true);
  await page.goto('/#/projects');
  const response = await page.request.get(`/api/v1/projects/${projectId}`);
  expect(response.ok()).toBe(true);
  const source = decodeProject(await response.json());
  expect(source.title).toBe('CI controlled historical adapter fixture (not extraction evidence)');
  expect(source.is_historical).toBe(true);
});

async function readEntry(page: Page, kind: HistoryKind, id: string) {
  const response = await page.request.get(`/api/v1/history/${kind}/${encodeURIComponent(id)}`);
  expect(response.ok()).toBe(true);
  const entry = decodeHistoryEntry(await response.json());
  expect(entry.kind).toBe(kind);
  expect(entry.id).toBe(id);
  return entry;
}
async function readList(page: Page, kind: HistoryKind, deleted: boolean, owner?: string) {
  const query = new URLSearchParams({
    kind,
    deleted: String(deleted),
    page: '1',
    page_size: '100',
  });
  if (owner) query.set('project_id', owner);
  const response = await page.request.get(`/api/v1/history?${query}`);
  expect(response.ok()).toBe(true);
  return decodeHistoryList(await response.json());
}
function historyRow(page: Page, entry: HistoryEntry) {
  // Opaque IDs are already validated by the API decoder. Titles can repeat
  // across real exports/attempts; never select an arbitrary same-title record.
  return page
    .getByRole('dialog')
    .locator(`li[data-history-kind="${entry.kind}"][data-history-id="${entry.id}"]`);
}
async function closeDialogs(page: Page) {
  // Topmost standard modal only, preserving keyboard/focus behavior.
  while (await page.getByRole('dialog').count()) {
    await page.getByRole('dialog').last().getByRole('button', { name: '关闭对话框' }).click();
  }
}
async function confirm(page: Page, entry: HistoryEntry, restoring = false) {
  const path = `/api/v1/history/${entry.kind}/${entry.id}/${restoring ? 'restore' : 'delete'}`;
  const modal = page.getByRole('dialog').last();
  await expect(modal).toContainText('不释放磁盘空间');
  const button = modal.getByRole('button', {
    name: restoring ? '确认恢复' : '确认移入回收站',
    exact: true,
  });
  await expect(button).toBeEnabled();
  const returned = page.waitForResponse(
    (response) =>
      response.request().method() === 'POST' && new URL(response.url()).pathname === path,
  );
  await button.click();
  const response = await returned;
  expect(response.ok()).toBe(true);
  expect(response.request().headers()['x-csrf-token']).toBeTruthy();
  expect(response.request().postDataJSON()).toEqual({ expected_revision: entry.revision });
  // A navigation/reload may discard a response body. Reconcile via GET only.
  const current = await readEntry(page, entry.kind, entry.id);
  expect(current.deleted_at === null).toBe(restoring);
  return current;
}
async function openTrash(page: Page, kind: HistoryKind) {
  await closeDialogs(page);
  await page.goto('/#/projects');
  await page.getByRole('button', { name: '回收站', exact: true }).click();
  await page.getByRole('combobox', { name: '回收站记录类型' }).selectOption(kind);
}
async function restoreFromTrash(page: Page, entry: HistoryEntry) {
  await openTrash(page, entry.kind);
  await historyRow(page, entry)
    .getByRole('button', { name: `恢复 ${entry.title}`, exact: true })
    .click();
  await confirm(page, await readEntry(page, entry.kind, entry.id), true);
  await closeDialogs(page);
}
async function ownedFailedProject(page: Page) {
  const response = await page.request.get(`/api/v1/jobs/${failedJobId}`);
  expect(response.ok()).toBe(true);
  const job = decodeJob(await response.json());
  expect(job.status).toBe('failed');
  const owner = await page.request.get(`/api/v1/projects/${job.project_id}`);
  expect(owner.ok()).toBe(true);
  const project = decodeProject(await owner.json());
  expect(project.title).toBe('Controlled real CLI failure');
  expect(project.is_historical).toBe(false);
  return { job, project };
}

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
  await page.getByRole('button', { name: '操作记录', exact: true }).click();
  await page
    .getByRole('dialog')
    .getByRole('button', { name: `删除 ${entry.title}`, exact: true })
    .click();
  await expect(page.getByRole('dialog').last()).toContainText('不卸载环境，也不改变环境就绪状态');
  await confirm(page, entry);
  await closeDialogs(page);
  await expect(page).not.toHaveURL(/operation=/);
  await page.reload();
  await page.getByRole('button', { name: '操作记录', exact: true }).click();
  await expect(
    page.getByRole('dialog').getByRole('button', { name: `删除 ${entry.title}`, exact: true }),
  ).toHaveCount(0);
  await page.getByRole('dialog').getByRole('button', { name: '回收站', exact: true }).click();
  await page
    .getByRole('dialog')
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
