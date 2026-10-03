import { expect, test } from '@playwright/test';
import { decodeResults } from '../src/api/decoders';

const projectId = process.env.PATENTSAR_E2E_SOURCE_PROJECT_ID;
for (const width of [1830, 390]) {
  test(`actual project activity colors, stable filtering and source focus at ${width}`, async ({
    page,
  }) => {
    test.skip(!projectId, 'Requires approved original observations; read-only');
    await page.setViewportSize({ width, height: width === 1830 ? 1050 : 844 });
    const errors: string[] = [];
    page.on('pageerror', (error) => errors.push(error.message));
    await page.goto(`/#/projects/${projectId}?page=79&tab=original&pdfWidth=28`);
    const table = page.getByRole('table');
    await expect(table).toBeVisible();
    const endpoint = `/api/v1/projects/${projectId}/results`;
    const first = decodeResults(
      await (await page.request.get(`${endpoint}?page=1&page_size=25`)).json(),
    );
    const columns = first.activity_columns!;
    const catalog = columns.map((column) => column.strength_scale);
    expect(catalog).toHaveLength(5);
    expect(catalog.every((scale) => scale && scale.direction !== 'unknown')).toBe(true);
    const ratio = columns.find((column) => column.name === 'Cereblon HTRF ratio')!;
    expect(ratio.strength_scale).toMatchObject({
      direction: 'lower',
      eligible: 16,
      strong_boundary: 0.09,
      medium_boundary: 0.13,
    });
    const kp4 = columns.find((column) => column.name === 'KP4 HuR degradation grade')!;
    expect(kp4.strength_scale).toMatchObject({
      direction: 'lower',
      eligible: 427,
      strong_boundary: 0,
      medium_boundary: 1,
    });
    const jhh7 = columns.find((column) => column.name === 'JHH7 HuR degradation grade')!;
    expect(jhh7.strength_scale).toMatchObject({
      direction: 'lower',
      eligible: 70,
      strong_boundary: 1,
      medium_boundary: 2,
    });
    const anti = columns.find((column) => column.name === 'Anti-proliferation activity grade')!;
    expect(anti.strength_scale).toMatchObject({
      direction: 'higher',
      strong_boundary: 3,
      medium_boundary: 2,
    });
    const labels = ['Compound 2', 'Compound 3', 'Compound 6'];
    for (const [index, label] of labels.entries()) {
      const original = first.items.find((item) => item.display_id === label)!;
      const row = table
        .locator('tbody tr')
        .filter({ has: page.getByLabel(`选择化合物 ${label}`, { exact: true }) });
      const ratioCell = row.locator(`td[data-activity-column="${ratio.id}"]`);
      const tier = ['none', 'strong', 'medium'][index]!;
      await expect(ratioCell).toHaveAttribute('data-activity-strength', tier);
      const background = await ratioCell.evaluate(
        (element) => getComputedStyle(element).backgroundColor,
      );
      expect(background).toBe(
        tier === 'strong'
          ? 'rgb(201, 232, 213)'
          : tier === 'medium'
            ? 'rgb(237, 247, 240)'
            : 'rgb(255, 255, 255)',
      );
      await expect(row.locator(`td[data-activity-column="${anti.id}"]`)).toHaveAttribute(
        'data-activity-strength',
        index === 0 ? 'none' : 'strong',
      );
      expect(original.activity_rank_values).toHaveLength(original.activities.length);
      expect(await row.locator('td.prediction-column[data-activity-strength]').count()).toBe(0);
    }
    for (const query of [
      'page=2&page_size=25',
      'q=Compound%203',
      'q=__no_such_source_observation__',
    ]) {
      const packet = decodeResults(await (await page.request.get(`${endpoint}?${query}`)).json());
      expect(packet.activity_columns).toEqual(columns);
    }
    await page.getByLabel('搜索结果', { exact: true }).fill('Compound 3');
    // Wait for the accepted UI result, not a transient request cancelled by query updates.
    await expect(table.getByLabel('选择化合物 Compound 2', { exact: true })).toHaveCount(0);
    const selectedRow = table
      .locator('tbody tr')
      .filter({ has: page.getByLabel('选择化合物 Compound 3', { exact: true }) });
    const selectedCell = selectedRow.locator(`td[data-activity-column="${ratio.id}"]`);
    await expect(selectedCell).toHaveAttribute('data-activity-strength', 'strong');
    await page.reload();
    await expect(selectedCell).toHaveAttribute('data-activity-strength', 'strong');
    await selectedCell.getByRole('button').click();
    await expect(page.getByLabel('原始文档页码')).toHaveValue('344');
    await expect(page.locator('[data-activity-focus]')).toHaveCount(1);
    await expect(
      page.getByRole('img', { name: '原始专利 PDF 第 344 页', exact: true }),
    ).toBeVisible();
    expect(
      await selectedCell.evaluate((element) => getComputedStyle(element).backgroundColor),
    ).toBe('rgb(201, 232, 213)');
    await selectedCell.hover();
    expect(
      await selectedCell.evaluate((element) => getComputedStyle(element).backgroundColor),
    ).toBe('rgb(201, 232, 213)');
    await page.getByLabel('搜索结果', { exact: true }).fill('');
    await expect(table.locator('tbody tr')).toHaveCount(25);
    await page.locator('.table-scroll').evaluate((element) => {
      element.scrollLeft = 0;
    });
    await page.screenshot({
      path: test.info().outputPath(`01-activity-colors-${width}.png`),
      fullPage: true,
    });
    expect(errors).toEqual([]);
  });
}
