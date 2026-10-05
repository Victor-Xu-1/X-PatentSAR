import { expect, test } from '@playwright/test';
import type { Locator } from '@playwright/test';
import { createHash } from 'node:crypto';

const historyId = process.env.PATENTSAR_E2E_HISTORY_PROJECT_ID;
const palette = {
  canvas: 'rgb(250, 249, 245)',
  surface: 'rgb(255, 254, 251)',
  subtle: 'rgb(247, 246, 242)',
  selected: 'rgb(227, 224, 215)',
  ink: 'rgb(20, 20, 19)',
  primary: 'rgb(48, 48, 46)',
  accent: 'rgb(201, 100, 66)',
  focus: 'rgb(163, 76, 48)',
};

async function expectReadableText(locator: Locator) {
  const contrast = await locator.evaluate((element) => {
    const linear = (value: number) => {
      const channel = value / 255;
      return channel <= 0.04045 ? channel / 12.92 : ((channel + 0.055) / 1.055) ** 2.4;
    };
    const luminance = (color: string) => {
      const channels = color
        .match(/[\d.]+/g)!
        .slice(0, 3)
        .map(Number)
        .map(linear);
      return channels[0]! * 0.2126 + channels[1]! * 0.7152 + channels[2]! * 0.0722;
    };
    const style = getComputedStyle(element);
    const foreground = luminance(style.color);
    const background = luminance(style.backgroundColor);
    return (Math.max(foreground, background) + 0.05) / (Math.min(foreground, background) + 0.05);
  });
  expect(contrast, 'Normal-size control text must retain WCAG AA contrast').toBeGreaterThanOrEqual(
    4.5,
  );
}

test('warm workspace style is consistent across navigation, management and the actual task page', async ({
  page,
}) => {
  await page.goto('/#/projects');
  await expect(page.getByRole('heading', { name: '最近文件', exact: true })).toBeVisible();
  await expect(page.locator('html')).toHaveCSS('background-color', palette.canvas);
  await expect(page.locator('.sidebar')).toHaveCount(0);
  await expect(page.locator('.user-avatar')).toHaveCount(0);
  await expect(page.locator('.brand strong')).toHaveCSS('font-family', /Georgia/);
  const mark = page.locator('img.brand-symbol');
  await expect(mark).toBeVisible();
  await expect
    .poll(() => mark.evaluate((element) => (element as HTMLImageElement).naturalWidth))
    .toBe(1254);
  await expect(mark).toHaveCSS('object-fit', 'contain');
  const original = await page.request.get((await mark.getAttribute('src'))!);
  expect(original.ok()).toBe(true);
  expect(
    createHash('sha256')
      .update(await original.body())
      .digest('hex'),
  ).toBe('1099f1a295921cc9e229995cd84aced5a2e1022e223bf6140f65d585f7b7d591');
  for (const rel of ['icon', 'apple-touch-icon']) {
    const icon = page.locator(`link[rel="${rel}"]`);
    await expect(icon).toHaveCount(1);
    expect(await icon.getAttribute('href')).toBe(await mark.getAttribute('src'));
    const response = await page.request.get((await icon.getAttribute('href'))!);
    expect(response.headers()['content-type']).toContain('image/png');
    expect(
      createHash('sha256')
        .update(await response.body())
        .digest('hex'),
    ).toBe('1099f1a295921cc9e229995cd84aced5a2e1022e223bf6140f65d585f7b7d591');
  }
  const active = page.getByRole('button', { name: '最近文件', exact: true });
  await expect(active).toHaveAttribute('aria-current', 'page');
  await expect(active).toHaveCSS('background-color', palette.selected);
  await expectReadableText(active);
  await page.getByRole('button', { name: '环境管理', exact: true }).click();
  await expect(page.getByRole('heading', { name: '环境管理' })).toHaveCSS('font-family', /Georgia/);
  await page.getByText('运行诊断', { exact: true }).click();
  await expect(page.locator('.runtime-table th').first()).toHaveCSS(
    'background-color',
    palette.subtle,
  );
  await page.getByRole('button', { name: '上传 PDF', exact: true }).click();
  await expect(page).toHaveURL(/#\/new-task$/);
  await expect(page.getByRole('heading', { name: 'PDF → 结构与活性表格' })).toBeVisible();
  await expect(page.getByRole('dialog')).toHaveCount(0);
  await expect(page.locator('.new-task-page')).toHaveCSS('background-color', 'rgba(0, 0, 0, 0)');
  await expect(page.locator('.upload-drop')).toHaveCSS('background-color', palette.subtle);
  await expect(page.getByRole('radio')).toHaveCount(0);
  await expect(page.getByLabel('原始专利 PDF 文件')).toBeFocused();
  await expect(page.locator('.task-advanced')).toHaveCount(0);
  await expect(page.getByLabel('项目名称（可选）')).toHaveCount(0);
  await expect(page.getByLabel('专利标识（可选）')).toHaveCount(0);
  await page.getByRole('button', { name: '最近文件', exact: true }).click();
  await expect(page.getByRole('heading', { name: '最近文件', exact: true })).toBeVisible();
});

test('actual result tables, metrics and review controls use the same quiet palette', async ({
  page,
}) => {
  test.skip(!historyId, 'Requires an isolated historical result import');
  await page.goto(`/#/projects/${historyId}`);
  const rows = page.locator('.results-table tbody tr');
  await expect(rows.first()).toBeVisible();
  await expect(page.getByLabel('项目真实统计')).toHaveCount(0);
  const toolbar = await page.getByLabel('结构列表工具栏').boundingBox();
  expect(toolbar!.height, 'Primary results have one compact toolbar').toBeLessThanOrEqual(38);
  await page.getByRole('button', { name: '列表选项' }).click();
  await page.getByText('结果与验收详情', { exact: true }).click();
  const cards = page.locator('.metric-card');
  await expect(cards).toHaveCount(6);
  for (const card of await cards.all()) {
    await expect(card).toHaveCSS('background-color', 'rgba(0, 0, 0, 0)');
    await expect(card).toHaveCSS('background-image', 'none');
    await expect(card.locator('strong')).toHaveCSS('font-family', /Georgia/);
  }
  await page.keyboard.press('Escape');
  await expect(page.getByLabel('项目真实统计')).toHaveCount(0);
  await expect(page.locator('.results-table th').first()).toHaveCSS(
    'background-color',
    palette.subtle,
  );
  const edit = rows.first().getByRole('button', { name: /^修正 / });
  await edit.click();
  const dialog = page.getByRole('dialog');
  await expect(dialog).toHaveCSS('background-color', palette.surface);
  await page.getByLabel('修正化合物编号').focus();
  await expect(page.getByLabel('修正化合物编号')).toHaveCSS('outline-color', palette.focus);
  const save = page.getByRole('button', { name: '保存修正' });
  await expect(save).toHaveCSS('background-color', palette.primary);
  await expectReadableText(save);
  await page.keyboard.press('Escape');
  await expect(dialog).toHaveCount(0);
  await expect(edit).toBeFocused();
  await page.screenshot({ path: test.info().outputPath('warm-result-workspace.png') });
});

test('populated mobile workspace contains its table and keeps dialogs and navigation usable', async ({
  page,
}) => {
  test.skip(!historyId, 'Requires an isolated historical result import');
  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto(`/#/projects/${historyId}`);
  const rows = page.locator('.results-table tbody tr');
  await expect(rows.first()).toBeVisible();
  expect(
    await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth + 2),
  ).toBe(true);
  const scroll = page.locator('.table-scroll');
  expect(await scroll.evaluate((element) => element.scrollWidth > element.clientWidth)).toBe(true);
  await rows
    .first()
    .getByRole('button', { name: /^修正 / })
    .click();
  const dialog = page.getByRole('dialog');
  await expect(dialog).toBeVisible();
  const box = await dialog.boundingBox();
  expect(box).not.toBeNull();
  expect(box!.x).toBeGreaterThanOrEqual(0);
  expect(box!.x + box!.width).toBeLessThanOrEqual(390);
  await page.keyboard.press('Escape');
  await expect(page.locator('.sidebar')).toHaveCount(0);
  await page.getByRole('button', { name: '环境管理', exact: true }).click();
  await expect(page.getByRole('heading', { name: '环境管理' })).toBeVisible();
  await expect(page.getByRole('button', { name: '环境管理', exact: true })).toHaveAttribute(
    'aria-current',
    'page',
  );
  expect(
    await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth + 2),
  ).toBe(true);
  await page.screenshot({ path: test.info().outputPath('warm-mobile-runtime.png') });
  await page.getByRole('button', { name: '上传 PDF', exact: true }).click();
  await expect(page).toHaveURL(/#\/new-task$/);
  await expect(page.getByLabel('原始专利 PDF 文件')).toBeFocused();
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth + 2)).toBe(
    true,
  );
  await expect(page.getByLabel('任务说明', { exact: true })).toHaveCount(0);
  await expect(page.locator('.task-advanced')).toHaveCount(0);
});
