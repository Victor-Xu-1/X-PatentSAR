import { expect, test } from '@playwright/test';
import { access, readFile, readdir } from 'node:fs/promises';
import { createHash } from 'node:crypto';

async function retainedBytes(paths: string[]): Promise<Record<string, string>> {
  const result: Record<string, string> = {};
  for (const path of paths) {
    const entries = await readdir(path, { withFileTypes: true }).catch(
      (error: NodeJS.ErrnoException) => {
        if (error.code === 'ENOTDIR') return null;
        throw error;
      },
    );
    if (entries === null)
      result[path] = createHash('sha256')
        .update(await readFile(path))
        .digest('hex');
    else
      Object.assign(
        result,
        await retainedBytes(
          entries
            .filter((entry) => entry.isDirectory() || entry.isFile())
            .map((entry) => path + '/' + entry.name),
        ),
      );
  }
  return result;
}

test('one clear spans all types/pages, cleans unreferenced files and retains shared/imported data', async ({
  page,
}) => {
  test.skip(
    process.env.PATENTSAR_E2E_HISTORY_MUTATIONS !== 'synthetic-isolated-state' ||
      process.env.PATENTSAR_E2E_TRASH_CLEAR_RECORDS !== '104',
  );
  const errors: string[] = [],
    writes: string[] = [];
  page.on('pageerror', (error) => errors.push(error.message));
  page.on('request', (request) => {
    if (request.method() !== 'GET') writes.push(new URL(request.url()).pathname);
  });
  const proof = JSON.parse(process.env.PATENTSAR_E2E_TRASH_FILE_PROOF ?? '{}') as {
    delete: string[];
    retain: string[];
  };
  expect(proof.delete).toHaveLength(3);
  const stateRoot = process.env.PATENTSAR_WEB_STATE_DIR!;
  for (const path of proof.delete) {
    expect(path.startsWith(stateRoot + '/')).toBe(true);
    await access(path);
  }
  const retained = await retainedBytes(proof.retain);
  await page.goto('/#/jobs');
  for (const width of [390, 800, 1672]) {
    await page.setViewportSize({ width, height: 1060 });
    await page
      .getByRole('combobox', { name: /^(Interface language|界面语言)$/ })
      .selectOption('en');
    await page.getByRole('button', { name: 'Trash', exact: true }).click();
    const trash = page.getByRole('dialog', { name: 'Trash', exact: true });
    await trash.getByRole('button', { name: 'Empty Trash', exact: true }).click();
    const confirmation = page.getByRole('dialog', { name: 'Empty Trash?', exact: true });
    await expect(
      confirmation.getByText('All record types and pages: 104 records.', { exact: true }),
    ).toBeVisible();
    await expect(
      confirmation.getByRole('button', { name: 'Confirm empty all', exact: true }),
    ).toBeEnabled();
    await confirmation.screenshot({
      path: test.info().outputPath(`trash-confirm-en-${width}.png`),
    });
    await confirmation.getByRole('button', { name: 'Cancel', exact: true }).click();
    await expect(trash.getByRole('button', { name: 'Empty Trash', exact: true })).toBeFocused();
    await trash.getByRole('button', { name: 'Close', exact: true }).click();
    await page
      .getByRole('combobox', { name: /^(Interface language|界面语言)$/ })
      .selectOption('zh-CN');
    await page.getByRole('button', { name: '回收站', exact: true }).click();
    await page
      .getByRole('dialog', { name: '回收站', exact: true })
      .getByRole('button', { name: '清空回收站', exact: true })
      .click();
    const zh = page.getByRole('dialog', { name: '清空回收站？', exact: true });
    await expect(
      zh.getByText('全部类型、全部分页，共 104 条记录。', { exact: true }),
    ).toBeVisible();
    await zh.screenshot({ path: test.info().outputPath(`trash-confirm-zh-${width}.png`) });
    await zh.getByRole('button', { name: '取消', exact: true }).click();
    const parent = page.getByRole('dialog', { name: '回收站', exact: true });
    await expect(parent.getByRole('button', { name: '清空回收站', exact: true })).toBeFocused();
    await parent.getByRole('button', { name: '关闭', exact: true }).click();
    expect(writes).toEqual([]);
  }
  await page.setViewportSize({ width: 1672, height: 1060 });
  await page.getByRole('combobox', { name: /^(Interface language|界面语言)$/ }).selectOption('en');
  await page.getByRole('button', { name: 'Trash', exact: true }).click();
  const trash = page.getByRole('dialog', { name: 'Trash', exact: true });
  await trash.getByRole('button', { name: 'Empty Trash', exact: true }).click();
  const confirmation = page.getByRole('dialog', { name: 'Empty Trash?', exact: true });
  await expect(
    confirmation.getByRole('button', { name: 'Confirm empty all', exact: true }),
  ).toBeEnabled();
  const response = page.waitForResponse(
    (value) =>
      value.url().endsWith('/api/v1/history/trash/clear') && value.request().method() === 'POST',
  );
  await confirmation.getByRole('button', { name: 'Confirm empty all', exact: true }).dblclick();
  const receipt = await (await response).json();
  expect(receipt.status).toBe('complete');
  expect(receipt.files_deleted).toBe(3);
  expect(receipt.files_total).toBe(3);
  await expect(
    confirmation.getByText('Permanently removed 104 records.', { exact: true }),
  ).toBeVisible();
  expect(writes).toEqual(['/api/v1/history/trash/clear']);
  for (const path of proof.delete)
    await expect(access(path)).rejects.toMatchObject({ code: 'ENOENT' });
  expect(await retainedBytes(proof.retain)).toEqual(retained);
  await confirmation.screenshot({ path: test.info().outputPath('trash-cleared-1672.png') });
  await confirmation.getByRole('button', { name: 'Close', exact: true }).click();
  await expect(trash.getByText('No records of this type in Trash.', { exact: true })).toBeVisible();
  for (const kind of ['project', 'job', 'export', 'environment_operation']) {
    await trash
      .getByRole('combobox', { name: 'Trash record type', exact: true })
      .selectOption(kind);
    await expect(
      trash.getByText('No records of this type in Trash.', { exact: true }),
    ).toBeVisible();
  }
  await trash.getByRole('button', { name: 'Empty Trash', exact: true }).click();
  const empty = page.getByRole('dialog', { name: 'Empty Trash?', exact: true });
  await expect(
    empty.getByText('All record types and pages: 0 records.', { exact: true }),
  ).toBeVisible();
  await expect(
    empty.getByRole('button', { name: 'Confirm empty all', exact: true }),
  ).toBeDisabled();
  for (const width of [390, 800, 1672]) {
    await page.setViewportSize({ width, height: 1060 });
    await empty.screenshot({ path: test.info().outputPath(`trash-empty-${width}.png`) });
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth + 1)).toBe(
      true,
    );
  }
  expect(errors).toEqual([]);
});
