import { expect, test } from '@playwright/test';

// Fresh controller-owned state only. UI preference writes never create a task,
// call a model, or change uploaded patent/source data.
for (const width of [390, 800, 1672]) {
  test(`installed bilingual navigation persists and keeps PDF selection at ${width}px`, async ({
    page,
  }) => {
    const writes: string[] = [];
    const errors: string[] = [];
    page.on('pageerror', (error) => errors.push(error.message));
    await page.route('**/api/v1/**', async (route) => {
      if (route.request().method() !== 'GET') {
        writes.push(new URL(route.request().url()).pathname);
        await route.abort('blockedbyclient');
      } else await route.continue();
    });
    await page.setViewportSize({ width, height: width === 390 ? 844 : 942 });
    await page.goto('/#/new-task');
    const language = page.getByRole('combobox', { name: 'Interface language', exact: true });
    await expect(language).toHaveValue('en');
    await expect(page.locator('html')).toHaveAttribute('lang', 'en');
    await page.getByLabel('Original patent PDF file', { exact: true }).setInputFiles({
      name: '中文原文-008B.pdf',
      mimeType: 'application/pdf',
      buffer: Buffer.from('%PDF-synthetic-selection-only'),
    });
    await language.selectOption('zh-CN');
    await expect(page.getByRole('heading', { name: '上传专利 PDF', exact: true })).toBeVisible();
    await page.getByRole('combobox', { name: '界面语言', exact: true }).selectOption('en');
    await expect(
      page.getByRole('heading', { name: 'Upload patent PDF', exact: true }),
    ).toBeVisible();
    await expect(page.getByText('中文原文-008B.pdf', { exact: true })).toBeVisible();
    expect(
      await page
        .getByLabel('Original patent PDF file', { exact: true })
        .evaluate((input) => (input as HTMLInputElement).files?.[0]?.name),
    ).toBe('中文原文-008B.pdf');
    await expect(page.locator('html')).toHaveAttribute('lang', 'en');
    await expect(
      page.getByRole('combobox', { name: 'Interface language', exact: true }),
    ).toHaveValue('en');
    for (const [caption, heading] of [
      ['Recent files', 'Recent files'],
      ['Tasks', 'Tasks'],
      ['Environment', 'Environment'],
    ] as const) {
      await page.locator('.topbar').getByRole('button', { name: caption, exact: true }).click();
      await expect(page.getByRole('heading', { name: heading, exact: true })).toBeVisible();
    }
    const panel = page.getByRole('region', { name: 'LLM API', exact: true });
    await panel.getByRole('button', { name: 'Configure', exact: true }).click();
    const dialog = page.getByRole('dialog', { name: 'LLM API settings', exact: true });
    await expect(dialog).toBeVisible();
    await expect(dialog.getByLabel('Review mode', { exact: true })).toHaveValue('off');
    await expect(dialog.getByRole('button', { name: 'Save', exact: true })).toBeDisabled();
    await dialog.getByRole('button', { name: 'Close dialog', exact: true }).click();
    await page.reload();
    await expect(
      page.getByRole('combobox', { name: 'Interface language', exact: true }),
    ).toHaveValue('en');
    await expect(page.getByRole('heading', { name: 'Environment', exact: true })).toBeVisible();
    const bounds = await page.evaluate(() => ({
      document: document.documentElement.scrollWidth <= innerWidth + 1,
      controls: [...document.querySelectorAll('.topbar button, .language-switch select')].every(
        (item) => {
          const box = item.getBoundingClientRect();
          return box.left >= 0 && box.right <= innerWidth + 1;
        },
      ),
    }));
    expect(bounds).toEqual({ document: true, controls: true });
    await page
      .getByRole('combobox', { name: 'Interface language', exact: true })
      .selectOption('zh-CN');
    await expect(page.getByRole('heading', { name: '环境管理', exact: true })).toBeVisible();
    await expect(page.locator('html')).toHaveAttribute('lang', 'zh-CN');
    expect(writes).toEqual([]);
    expect(errors).toEqual([]);
  });
}

test('installed table localization preserves original IDs, sources and query state', async ({
  page,
}) => {
  const id = process.env.PATENTSAR_E2E_SOURCE_PROJECT_ID;
  test.skip(!id, 'Requires a controlled read-only historical adapter fixture');
  const writes: string[] = [];
  await page.route('**/api/v1/**', async (route) => {
    if (route.request().method() !== 'GET') {
      writes.push(route.request().url());
      await route.abort();
    } else await route.continue();
  });
  await page.goto(`/#/projects/${id}?page=1&tab=original`);
  const record = page.locator('tbody tr').first();
  await expect(record).toBeVisible();
  const original = await record
    .locator('.compound-cell, .compound-label, .frozen-compound')
    .first()
    .innerText();
  const before = page.url();
  await page
    .getByRole('combobox', { name: 'Interface language', exact: true })
    .selectOption('zh-CN');
  await page.getByRole('combobox', { name: '界面语言', exact: true }).selectOption('en');
  await expect(page.getByRole('columnheader', { name: /Original ID/ })).toBeVisible();
  expect(page.url()).toBe(before);
  expect(
    await record.locator('.compound-cell, .compound-label, .frozen-compound').first().innerText(),
  ).toBe(original);
  await page.reload();
  await expect(page.getByRole('combobox', { name: 'Interface language', exact: true })).toHaveValue(
    'en',
  );
  expect(writes).toEqual([]);
});
