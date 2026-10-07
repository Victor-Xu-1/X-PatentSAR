import { expect } from '@playwright/test';
import type { Page } from '@playwright/test';

/** Move the selected drawing through visible tools; preserve its chemical graph. */
export async function moveDrawing(page: Page) {
  const frame = page.frameLocator('iframe[title="Ketcher 结构绘制与预览"]');
  await frame.getByRole('button', { name: 'Rectangle Selection (Shift+Tab)', exact: true }).click();
  const canvas = frame.getByRole('application').getByRole('img');
  await canvas.click({ position: { x: 10, y: 10 } });
  await page.keyboard.press('Control+a');
  const label = canvas
    .locator('text')
    .filter({ hasText: /[ONF]|Cl/ })
    .first();
  await expect(label).toBeVisible();
  const box = await label.boundingBox();
  if (!box) throw new Error('Controlled chemical reference has no visible atom label');
  const x = box.x + box.width / 2;
  const y = box.y + box.height / 2;
  await page.mouse.move(x, y);
  await page.mouse.down();
  await page.mouse.move(x + 16, y + 10, { steps: 4 });
  await page.mouse.up();
}

/** Draw a controlled ethanol reference through Ketcher's real atom/bond tools. */
export async function drawEthanol(page: Page) {
  const frame = page.frameLocator('iframe[title="Ketcher 结构绘制与预览"]');
  await expect(page.getByRole('button', { name: '保存修正', exact: true })).toBeEnabled();
  await frame.getByRole('button', { name: 'Clear Canvas (Ctrl+Del)', exact: true }).click();
  await expect(page.getByRole('button', { name: '保存修正', exact: true })).toBeEnabled();
  await frame.getByRole('button', { name: 'Single Bond (1)', exact: true }).click();
  const canvas = frame.getByRole('application').getByRole('img');
  const box = await canvas.boundingBox();
  if (!box || box.width < 420 || box.height < 160)
    throw new Error('Drawing reference requires a desktop canvas');
  const start = { x: box.x + box.width * 0.35, y: box.y + box.height * 0.5 };
  const middle = { x: start.x + 40, y: start.y - 23 };
  const end = { x: middle.x + 40, y: start.y };
  for (const [from, to] of [
    [start, middle],
    [middle, end],
  ]) {
    await page.mouse.move(from!.x, from!.y);
    await page.mouse.down();
    await page.mouse.move(to!.x, to!.y, { steps: 5 });
    await page.mouse.up();
  }
  await frame.getByRole('button', { name: 'O', exact: true }).click();
  await page.mouse.click(end.x, end.y);
  await expect(page.getByRole('button', { name: '保存修正', exact: true })).toBeEnabled();
}
