import { expect, test } from '@playwright/test';
import { writeFile } from 'node:fs/promises';
import { decodeResults } from '../src/api/decoders';
import { EDITOR_CHANNEL } from '../src/features/structure-editor/protocol';

const projectId = process.env.PATENTSAR_E2E_SOURCE_PROJECT_ID;
for (const viewport of [
  { width: 1672, height: 942 },
  { width: 1280, height: 800 },
  { width: 390, height: 844 },
]) {
  test(`minimal drawing and column edit; larger borderless structures at ${viewport.width}`, async ({
    page,
  }) => {
    test.skip(!projectId, 'Requires an explicitly approved real project');
    await page.setViewportSize(viewport);
    const errors: string[] = [],
      editorRequests: string[] = [];
    page.on('pageerror', (error) => errors.push(error.message));
    page.on('request', (request) => {
      if (/ketcher\.html|assets\/(structureEditor|indigo)/.test(request.url()))
        editorRequests.push(request.url());
    });
    await page.goto(`/#/projects/${projectId}?page=79&tab=annotations`);
    await expect(page.getByRole('table')).toBeVisible();
    expect(editorRequests).toEqual([]);
    const data = decodeResults(
      await (
        await page.request.get(`/api/v1/projects/${projectId}/results?page=1&page_size=25`)
      ).json(),
    );
    const row = data.items.find((item) => item.display_id === 'Compound 3') ?? data.items[0]!;
    const thumbnail = page.locator(`tr[data-compound="${row.id}"] .crop-button`);
    const image = thumbnail.getByRole('img');
    await expect(image).toBeVisible();
    await expect
      .poll(() => image.evaluate((node) => (node as HTMLImageElement).naturalWidth))
      .toBeGreaterThan(0);
    const geometry = await thumbnail.evaluate((node) => {
      const style = getComputedStyle(node),
        rectangle = node.getBoundingClientRect();
      return {
        border: style.borderWidth,
        radius: style.borderRadius,
        width: rectangle.width,
        height: rectangle.height,
      };
    });
    expect(geometry.border).toBe('0px');
    expect(geometry.radius).toBe('0px');
    expect(geometry.width).toBeGreaterThan(80);
    expect(geometry.height).toBeGreaterThan(64);
    await page.getByLabel(`修正 ${row.display_id}`, { exact: true }).click();
    const dialog = page.getByRole('dialog');
    await expect(page.getByRole('button', { name: '保存修正', exact: true })).toBeEnabled();
    const host = page.getByLabel('结构式绘制区域', { exact: true });
    await expect(host).toBeVisible();
    const frame = page.frameLocator('iframe[title="Ketcher 结构绘制与预览"]');
    await expect(frame.getByRole('application')).toBeVisible();
    await expect(frame.getByRole('application').getByRole('img')).toBeVisible();
    await expect(frame.getByRole('button', { name: /^Save as/ })).toBeHidden();
    await expect(frame.getByRole('button', { name: 'Add Image', exact: true })).toBeHidden();
    expect(editorRequests.some((url) => url.includes('ketcher.html'))).toBe(true);
    for (const name of ['MW', 'LogP', 'TPSA', 'HBD', 'HBA', 'LogS'])
      await expect(dialog.getByLabel(`修正 ${name}`, { exact: true })).toBeVisible();
    expect(await dialog.locator('textarea,pre,details').count()).toBe(0);
    await expect(dialog.getByRole('button', { name: '复核注记' })).toHaveCount(0);
    await expect(dialog.getByRole('button', { name: '恢复原始值' })).toHaveCount(0);
    await expect(dialog.locator('.error-notice')).toHaveCount(0);
    await dialog.screenshot({ path: test.info().outputPath(`editor-${viewport.width}.png`) });
    await test.info().attach('drawing-dom', {
      body: await host.evaluate((node) => node.outerHTML),
      contentType: 'text/html',
    });
    await page.getByRole('button', { name: '取消', exact: true }).click();
    await expect(dialog).toHaveCount(0);
    await page.screenshot({
      path: test.info().outputPath(`borderless-structures-${viewport.width}.png`),
      fullPage: true,
    });
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth + 2)).toBe(
      true,
    );
    expect(errors).toEqual([]);
  });
}

test('local Ketcher round trips preserve stereo, isotope, charge and salt fragments', async ({
  page,
}) => {
  test.skip(!projectId, 'Requires an explicitly approved source project');
  const references = [
    '[13CH3][C@H](O)C(=O)[O-].[Na+]',
    'F/C=C/F',
    '[NH3+]CC(=O)[O-]',
    'C[C@@H](F)Cl',
  ];
  const records: { input: string; smiles: string; molfile: string }[] = [];
  await page.goto(`/#/projects/${projectId}`);
  await expect(page.getByRole('table')).toBeVisible();
  const data = decodeResults(
    await (
      await page.request.get(`/api/v1/projects/${projectId}/results?page=1&page_size=25`)
    ).json(),
  );
  const row = data.items.find((item) => item.display_id === 'Compound 3') ?? data.items[0]!;
  for (const input of references) {
    await page.getByLabel(`修正 ${row.display_id}`, { exact: true }).click();
    await expect(page.getByRole('button', { name: '保存修正', exact: true })).toBeEnabled();
    // The isolated test supplies bounded reference inputs through the editor's
    // same-origin public bridge, not a global SDK hook or a patent result write.
    await page.evaluate(
      ({ channel, smiles }) => {
        const iframe = document.querySelector<HTMLIFrameElement>(
          'iframe[title="Ketcher 结构绘制与预览"]',
        )!;
        const state = { loaded: false, value: null as { smiles: string; molfile: string } | null };
        Object.assign(window, { __editorReference: state });
        const receive = (event: MessageEvent) => {
          if (
            event.origin !== location.origin ||
            event.source !== iframe.contentWindow ||
            event.data?.channel !== channel
          )
            return;
          if (event.data.kind === 'loaded') state.loaded = true;
          if (event.data.kind === 'change') {
            state.value = event.data.value;
            window.removeEventListener('message', receive);
          }
        };
        window.addEventListener('message', receive);
        iframe.contentWindow!.postMessage(
          { channel, kind: 'load', smiles, molfile: null },
          location.origin,
        );
      },
      { channel: EDITOR_CHANNEL, smiles: input },
    );
    await expect
      .poll(() =>
        page.evaluate(
          () =>
            (window as unknown as { __editorReference: { loaded: boolean } }).__editorReference
              .loaded,
        ),
      )
      .toBe(true);
    await page
      .frameLocator('iframe[title="Ketcher 结构绘制与预览"]')
      .getByRole('button', { name: 'Clean Up (Ctrl+Shift+L)', exact: true })
      .click();
    await expect
      .poll(() =>
        page.evaluate(
          () =>
            (window as unknown as { __editorReference: { value: unknown } }).__editorReference
              .value,
        ),
      )
      .not.toBeNull();
    const value = await page.evaluate(
      () =>
        (window as unknown as { __editorReference: { value: { smiles: string; molfile: string } } })
          .__editorReference.value,
    );
    expect(value.molfile).toContain('V3000');
    records.push({ input, ...value });
    await page.getByRole('button', { name: '取消', exact: true }).click();
  }
  await writeFile(
    test.info().outputPath('native-chemical-roundtrips.json'),
    JSON.stringify(records, null, 2),
  );
  await test.info().attach('native-chemical-roundtrips', {
    body: JSON.stringify(records),
    contentType: 'application/json',
  });
});
