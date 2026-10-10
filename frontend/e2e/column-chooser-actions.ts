import { expect } from '@playwright/test';
import type { Locator } from '@playwright/test';

/** The controlled SAR fixture has distinct column names; duplicate-context behavior is separate. */
export async function checkDistinctColumnChoices(chooser: Locator) {
  await expect(chooser.getByRole('textbox', { name: 'Find column', exact: true })).toBeFocused();
  const first = chooser.locator('.column-chooser-choice').first();
  const geometry = await first.evaluate((element) => {
    const box = element.getBoundingClientRect();
    const check = element.querySelector('input')!.getBoundingClientRect();
    const text = element.querySelector('span')!.getBoundingClientRect();
    return {
      horizontal: check.right <= text.left,
      aligned: Math.abs(check.top + check.height / 2 - text.top - text.height / 2) < 2,
      height: box.height,
    };
  });
  expect(geometry.horizontal).toBe(true);
  expect(geometry.aligned).toBe(true);
  expect(geometry.height).toBeGreaterThanOrEqual(40);
  expect(geometry.height).toBeLessThanOrEqual(52);
  const details = chooser.getByRole('button', { name: 'Column details', exact: true });
  await expect(details).toHaveAttribute('aria-expanded', 'false');
  await expect(chooser.locator('.column-chooser-context')).toHaveCount(0);
  await details.click();
  await expect(details).toHaveAttribute('aria-expanded', 'true');
  expect(await chooser.locator('.column-chooser-context').count()).toBeGreaterThan(0);
  await details.click();
  await expect(chooser.locator('.column-chooser-context')).toHaveCount(0);
}
