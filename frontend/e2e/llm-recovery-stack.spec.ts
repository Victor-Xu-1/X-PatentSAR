import { expect, test } from '@playwright/test';

test('installed API/browser renews one isolated task without provider calls or automatic resume', async ({
  page,
}) => {
  test.skip(
    process.env.PATENTSAR_E2E_RECOVERY_STACK !== 'synthetic-isolated-state',
    'Requires a freshly generated owned control workspace',
  );
  const id = process.env.PATENTSAR_E2E_RECOVERY_JOB_ID;
  if (!id) throw new Error('Missing isolated recovery job');
  const writes: string[] = [];
  const external: string[] = [];
  const errors: string[] = [];
  page.on('pageerror', (error) => errors.push(error.message));
  page.on('request', (request) => {
    if (request.method() !== 'GET') writes.push(new URL(request.url()).pathname);
    if (new URL(request.url()).origin !== new URL(process.env.PATENTSAR_E2E_BASE_URL!).origin)
      external.push(request.url());
  });
  await page.goto('/#/jobs');
  const record = page
    .locator('.job-record')
    .filter({ has: page.getByText(`任务 ${id}`, { exact: true }) });
  await record.locator('summary').first().click();
  await expect(record.getByText('剩余调用 7 次', { exact: false })).toBeVisible();
  await record.getByRole('button', { name: '更新 API 授权', exact: true }).click();
  const dialog = page.getByRole('dialog', { name: '更新此任务的 API 授权？' });
  await expect(dialog.getByText('synthetic-transport-only', { exact: true })).toBeVisible();
  const response = page.waitForResponse(
    (reply) =>
      reply.request().method() === 'POST' && reply.url().endsWith(`/jobs/${id}/llm-authorization`),
  );
  await dialog.getByRole('button', { name: '确认更新授权', exact: true }).click();
  const reply = await response;
  expect(reply.status()).toBe(200);
  await expect(dialog).toHaveCount(0);
  // The successful write refreshes/unmounts its page controls. Read durable
  // authenticated state independently: a CDP response body can be evicted by
  // that refresh even when the application consumed it successfully.
  const persisted = await page.request.get(`/api/v1/jobs/${id}`);
  expect(persisted.ok()).toBe(true);
  const job = await persisted.json();
  expect(job.status).toBe('cancelled');
  expect(job.llm_recovery).toMatchObject({
    status: 'ready',
    remaining_calls: 7,
    can_reauthorize: false,
  });
  await page.reload();
  await record.locator('summary').first().click();
  await expect(record.getByText('剩余调用 7 次', { exact: false })).toBeVisible();
  expect(writes).toEqual([`/api/v1/jobs/${id}/llm-authorization`]);
  expect(external).toEqual([]);
  expect(errors).toEqual([]);
});
