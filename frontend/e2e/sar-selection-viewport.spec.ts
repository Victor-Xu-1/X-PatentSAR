import { expect, test, type Page, type TestInfo } from '@playwright/test';
import { randomUUID } from 'node:crypto';

async function syntheticSnapshot(page: Page) {
  const origin = new URL(process.env.PATENTSAR_E2E_BASE_URL!);
  expect(['127.0.0.1', 'localhost', '[::1]']).toContain(origin.hostname);
  expect(Number(origin.port)).toBeGreaterThanOrEqual(18766);
  expect(Number(origin.port)).toBeLessThanOrEqual(18866);
  const project = process.env.PATENTSAR_E2E_SOURCE_PROJECT_ID;
  expect(project).toMatch(/^[a-f0-9]{32}$/);
  const initialized = page.waitForResponse(
    (response) =>
      response.request().method() === 'GET' &&
      new URL(response.url()).pathname === '/api/v1/sar/datasets' &&
      response.ok(),
  );
  await page.goto('/#/sar');
  // Let the UI's single bootstrap settle before reading its current session.
  // Creating a second session concurrently can replace the context's cookie.
  await initialized;
  const session = await page.request.get('/api/v1/session');
  expect(session.ok()).toBe(true);
  const created = await page.request.post('/api/v1/sar/datasets/project', {
    headers: { Origin: origin.origin, 'X-CSRF-Token': (await session.json()).csrf_token },
    data: { project_id: project, request_id: randomUUID().replaceAll('-', '') },
  });
  expect(created.status()).toBe(201);
  const dataset = await created.json();
  expect(dataset.row_count).toBe(30);
  expect(dataset.eligible_count).toBeGreaterThan(0);
  // A full document load reads the new snapshot list. Hash-only navigation
  // would retain the pre-snapshot list because this controlled API setup did
  // not pass through the UI's explicit list invalidation.
  await page.goto('/?controlled-snapshot=' + dataset.id + '#/sar?dataset=' + dataset.id);
  await expect(
    page.getByRole('combobox', { name: 'SAR datasets', exact: true }).locator('option:checked'),
  ).toHaveText(dataset.title);
  return dataset;
}

async function picker(page: Page, mode: 'study' | 'advanced') {
  if (mode === 'advanced') {
    await page.getByText('Single-reference comparison (advanced)', { exact: true }).click();
  } else {
    const setup = page.getByRole('region', { name: 'Study setup', exact: true });
    await setup.locator('.sar-context-choice input').first().check();
    await setup
      .getByRole('combobox', { name: 'Activity direction', exact: true })
      .selectOption('lower');
    await setup.getByRole('button', { name: 'Continue', exact: true }).click();
    await setup.getByText('Add a named selection', { exact: true }).click();
  }
  return page.getByRole('region', { name: 'Choose reference molecule', exact: true });
}

async function capture(page: Page, info: TestInfo, name: string) {
  await page.screenshot({ path: info.outputPath(name + '.png'), animations: 'disabled' });
}

// Only the explicit snapshot above writes owned synthetic data. No region save,
// analysis job, extraction, environment operation or provider call is exercised.
for (const width of [390, 800, 1672]) {
  for (const mode of ['study', 'advanced'] as const) {
    test(`${mode} reference picker reveals the atom work area at ${width}px`, async ({
      page,
    }, info) => {
      test.skip(process.env.PATENTSAR_E2E_SAR_MUTATIONS !== 'synthetic-isolated-state');
      const errors: string[] = [],
        writes: string[] = [];
      page.on('pageerror', (error) => errors.push(error.message));
      await page.route('**/api/v1/**', async (route) => {
        if (route.request().method() !== 'GET') {
          writes.push(new URL(route.request().url()).pathname);
          await route.abort();
        } else await route.continue();
      });
      await page.setViewportSize({ width, height: width === 390 ? 844 : 1060 });
      await page.emulateMedia({ reducedMotion: 'reduce' });
      const dataset = await syntheticSnapshot(page);
      const browser = await picker(page, mode);
      const scroll = browser.locator('.sar-table-scroll');
      await expect(
        browser.getByRole('button', { name: 'Reference', exact: true }).first(),
      ).toBeEnabled();
      const bounds = await scroll.boundingBox();
      expect(bounds!.height).toBeLessThanOrEqual(361);
      expect(await scroll.evaluate((element) => element.scrollHeight > element.clientHeight)).toBe(
        true,
      );
      await scroll.evaluate((element) => {
        element.scrollLeft = element.scrollWidth;
      });
      const first = browser.locator('tbody tr').first();
      const label = await first.getByRole('rowheader').innerText();
      const reference = first.getByRole('button', { name: 'Reference', exact: true });
      if (width === 390) {
        await expect(first.locator('td').nth(1)).toBeVisible();
        const details = first.locator('td > details > summary');
        expect(
          await details.evaluate((element) => {
            const box = element.getBoundingClientRect(),
              scroll = element.closest('.sar-table-scroll')!.getBoundingClientRect();
            return box.left >= scroll.left && box.right <= scroll.right;
          }),
        ).toBe(true);
      }
      expect(
        await reference.evaluate((button) => {
          const text = document.createRange();
          text.selectNodeContents(button);
          return text.getClientRects().length;
        }),
      ).toBe(1);
      await reference.scrollIntoViewIfNeeded();
      expect(
        await reference.evaluate((button) => {
          const box = button.getBoundingClientRect();
          return (
            document
              .elementFromPoint(box.x + box.width / 2, box.y + box.height / 2)
              ?.closest('button') === button
          );
        }),
      ).toBe(true);
      await capture(page, info, '01-picker');
      await reference.click();
      await expect(browser).toBeHidden();
      const panel = page.getByRole('region', { name: 'Select variable region', exact: true });
      await expect(
        panel.getByRole('heading', { name: 'Select variable region · ' + label, exact: true }),
      ).toBeVisible();
      await expect(panel.locator('.sar-atom').first()).toBeEnabled();
      await expect(panel).toBeFocused();
      const geometry = await panel.locator('.sar-drawing').evaluate((drawing) => {
        const box = drawing.getBoundingClientRect();
        return {
          height: box.height,
          visible: Math.max(0, Math.min(box.bottom, innerHeight) - Math.max(box.top, 0)),
        };
      });
      expect(geometry.visible / geometry.height).toBeGreaterThan(0.9);
      const atoms = panel.locator('.sar-atom');
      expect(
        await atoms.last().evaluate((button) => getComputedStyle(button).backgroundColor),
      ).toBe('rgba(0, 0, 0, 0)');
      expect(await atoms.last().evaluate((button) => getComputedStyle(button).borderTopColor)).toBe(
        'rgba(0, 0, 0, 0)',
      );
      const atomLabel = await atoms.first().getAttribute('aria-label');
      await atoms.first().click();
      await expect(atoms.first()).toHaveAttribute('aria-pressed', 'true');
      if (mode === 'study')
        await panel.getByLabel('Selection name', { exact: true }).fill('Original 原文 draft');
      await capture(page, info, '02-selected');
      await page.getByRole('button', { name: 'Change reference', exact: true }).click();
      await browser.getByLabel('Search identifiers or SMILES', { exact: true }).fill(label);
      await page.getByRole('button', { name: 'Return to selection', exact: true }).click();
      await expect(atoms.first()).toHaveAttribute('aria-pressed', 'true');
      if (mode === 'study')
        await expect(panel.getByLabel('Selection name', { exact: true })).toHaveValue(
          'Original 原文 draft',
        );
      await page
        .getByRole('combobox', { name: 'Interface language', exact: true })
        .selectOption('zh-CN');
      const chinese = page.getByRole('region', { name: '选择变化区域', exact: true });
      await expect(
        chinese.getByRole('heading', { name: '选择变化区域 · ' + label, exact: true }),
      ).toBeVisible();
      await expect(chinese.locator('.sar-atom').first()).toHaveAttribute('aria-pressed', 'true');
      if (mode === 'study')
        await expect(chinese.getByLabel('区域名称', { exact: true })).toHaveValue(
          'Original 原文 draft',
        );
      const jobs = await page.request.get('/api/v1/sar/datasets/' + dataset.id + '/jobs');
      expect((await jobs.json()).items).toEqual([]);
      expect(
        await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth + 1),
      ).toBe(true);
      expect(atomLabel).toMatch(/^Atom \d+ \([A-Za-z]+\)$/);
      expect(errors).toEqual([]);
      expect(writes).toEqual([]);
    });
  }
}
