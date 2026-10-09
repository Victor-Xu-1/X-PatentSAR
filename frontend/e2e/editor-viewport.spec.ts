import { expect, test } from '@playwright/test';

for (const width of [390, 800, 1672]) {
  test(`native chemistry viewport fit and unchanged source at ${width}px`, async ({ page }) => {
    const source = process.env.PATENTSAR_E2E_SOURCE_PROJECT_ID;
    expect(source).toBeTruthy();
    const writes: string[] = [],
      errors: string[] = [];
    page.on('pageerror', (error) => errors.push(error.message));
    await page.route('**/api/v1/**', async (route) => {
      const localRead =
        route.request().method() === 'POST' &&
        new URL(route.request().url()).pathname === '/api/v1/chemistry/structure';
      if (route.request().method() !== 'GET' && !localRead) {
        writes.push(route.request().url());
        await route.abort();
      } else await route.continue();
    });
    await page.setViewportSize({ width, height: width === 390 ? 844 : 1060 });
    await page.goto('/#/projects/' + source);
    const row = page.locator('.results-table tbody tr').first();
    await expect(row).toBeVisible();
    const original = await row.allTextContents();
    const opener = row.getByRole('button', { name: /^Correct / });
    await opener.click();
    const correction = page.getByRole('dialog', { name: /^Correction/ });
    await expect(
      correction.getByRole('button', { name: 'Fit to canvas', exact: true }),
    ).toBeEnabled({ timeout: 30000 });
    // Exercise the same parent-load contract using synthetic long chemistry,
    // not injected SDK operations, another editor, or modified source records.
    await page
      .locator('iframe[title="Ketcher structure drawing and preview"]')
      .evaluate((frame) => {
        (frame as HTMLIFrameElement).contentWindow!.postMessage(
          {
            channel: 'x-patentsar.structure-editor.v1',
            kind: 'load',
            smiles: 'CO'.repeat(20) + 'C[C@H](O)c1ccc(Cl)cc1',
            molfile: null,
          },
          location.origin,
        );
      });
    const fit = correction.getByRole('button', { name: 'Fit to canvas', exact: true });
    const canvas = page.frameLocator('dialog.correction-dialog iframe').locator('svg');
    await expect
      .poll(
        () =>
          canvas.evaluateAll((elements) => {
            const svg = elements.find((element) => element.getBoundingClientRect().height > 150);
            return svg
              ? Array.from(svg.querySelectorAll('text')).filter((label) =>
                  /^O(?:H)?$/.test(label.textContent?.trim() ?? ''),
                ).length
              : 0;
          }),
        { timeout: 30000 },
      )
      .toBeGreaterThan(15);
    const measure = () =>
      canvas.evaluateAll((elements) => {
        const svg = elements.find((element) => element.getBoundingClientRect().height > 150) as
          SVGSVGElement | undefined;
        if (!svg) return false;
        const box = svg.getBBox(),
          view = svg.viewBox.baseVal;
        return (
          box.width > 10 &&
          box.height > 10 &&
          box.x >= view.x - 2 &&
          box.y >= view.y - 2 &&
          box.x + box.width <= view.x + view.width + 2 &&
          box.y + box.height <= view.y + view.height + 2
        );
      });
    await expect.poll(measure, { timeout: 30000 }).toBe(true);
    await fit.focus();
    await page.keyboard.press('Enter');
    await expect.poll(measure).toBe(true);
    await page
      .getByRole('combobox', { name: 'Interface language', exact: true })
      .selectOption('zh-CN');
    await expect(page.getByRole('button', { name: '适应画布', exact: true })).toBeEnabled();
    await expect.poll(measure).toBe(true);
    await page.getByRole('combobox', { name: '界面语言', exact: true }).selectOption('en');
    for (const metric of ['MW', 'LogP', 'TPSA', 'HBD', 'HBA', 'LogS'])
      await expect(correction.getByLabel(`Correct ${metric}`, { exact: true })).toBeVisible();
    await correction.screenshot({ path: test.info().outputPath(`fit-correction-${width}.png`) });
    await page.setViewportSize({ width: width === 390 ? 800 : 390, height: 844 });
    await expect.poll(measure).toBe(true);
    await correction.getByRole('button', { name: 'Cancel', exact: true }).click();
    await expect(opener).toBeFocused();
    await expect(row).toHaveText(original.join(''));
    expect(writes).toEqual([]);
    expect(errors).toEqual([]);
  });
}
