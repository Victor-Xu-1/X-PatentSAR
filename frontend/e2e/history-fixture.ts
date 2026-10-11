import { expect, test } from '@playwright/test';
import type { Page } from '@playwright/test';
import { decodeJob, decodeProject } from '../src/api/decoders';
import { decodeHistoryEntry, decodeHistoryList } from '../src/api/historyDecoders';
import type { HistoryEntry, HistoryKind } from '../src/api/historyTypes';

export const projectId = process.env.PATENTSAR_E2E_HISTORY_PROJECT_ID;
const failedJobId = process.env.PATENTSAR_E2E_FAILED_JOB_ID;
export const environmentId = process.env.PATENTSAR_E2E_ENVIRONMENT_OPERATION_ID;
const isolated = process.env.PATENTSAR_E2E_HISTORY_MUTATIONS === 'synthetic-isolated-state';
export const baseURL = process.env.PATENTSAR_E2E_BASE_URL;
const output = process.env.PATENTSAR_E2E_OUTPUT_DIR;

// Only the controller's synthetic fixture is authorized. No copied patent,
// production lookup, success interception, service startup or model execution.
export async function prepareHistory(page: Page) {
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
  await page
    .getByRole('combobox', { name: 'Interface language', exact: true })
    .selectOption('zh-CN');
  expect(response.ok()).toBe(true);
  const source = decodeProject(await response.json());
  expect(source.title).toBe('CI controlled historical adapter fixture (not extraction evidence)');
  expect(source.is_historical).toBe(true);
}

export async function readEntry(page: Page, kind: HistoryKind, id: string) {
  const response = await page.request.get(`/api/v1/history/${kind}/${encodeURIComponent(id)}`);
  expect(response.ok()).toBe(true);
  const entry = decodeHistoryEntry(await response.json());
  expect(entry.kind).toBe(kind);
  expect(entry.id).toBe(id);
  return entry;
}
export async function readList(page: Page, kind: HistoryKind, deleted: boolean, owner?: string) {
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
export function historyRow(page: Page, entry: HistoryEntry) {
  // Opaque IDs are already validated by the API decoder. Titles can repeat
  // across real exports/attempts; never select an arbitrary same-title record.
  return page
    .getByRole('dialog')
    .locator(`li[data-history-kind="${entry.kind}"][data-history-id="${entry.id}"]`);
}
export async function closeDialogs(page: Page) {
  // A successful delete can unmount its row/modal between a locator count and
  // click. Native Escape targets the current modal; do not wait on a stale row.
  const open = page.locator('dialog[open]');
  for (let level = 0; level < 3; level++) {
    const before = await open.count();
    if (before === 0) return;
    await expect
      .poll(() =>
        open.evaluateAll((dialogs) => {
          const top = dialogs.at(-1);
          if (!top) return true;
          const close = top.querySelector('button[aria-label="关闭对话框"]');
          return close instanceof HTMLButtonElement && !close.disabled;
        }),
      )
      .toBe(true);
    await page.keyboard.press('Escape');
    await expect.poll(() => open.count()).toBeLessThan(before);
  }
  await expect(open).toHaveCount(0);
}
export async function confirm(page: Page, entry: HistoryEntry, restoring = false) {
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
export async function openTrash(page: Page, kind: HistoryKind) {
  await closeDialogs(page);
  await page.goto('/#/projects');
  await page.getByRole('button', { name: '回收站', exact: true }).click();
  await page.getByRole('combobox', { name: '回收站记录类型' }).selectOption(kind);
}
export async function restoreFromTrash(page: Page, entry: HistoryEntry) {
  await openTrash(page, entry.kind);
  await historyRow(page, entry)
    .getByRole('button', { name: `恢复 ${entry.title}`, exact: true })
    .click();
  await confirm(page, await readEntry(page, entry.kind, entry.id), true);
  await closeDialogs(page);
}
export async function ownedFailedProject(page: Page) {
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
