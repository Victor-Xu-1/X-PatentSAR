import { expect, test } from '@playwright/test';
import { readFile, writeFile } from 'node:fs/promises';
import { EDITOR_CHANNEL } from '../src/features/structure-editor/protocol';

const projectId = process.env.PATENTSAR_E2E_SOURCE_PROJECT_ID;
const referencePath = process.env.PATENTSAR_E2E_STEREO_REFERENCES;

test('unknown tetrahedral and double-bond drawings survive native edit/save/reopen/export', async ({
  page,
}) => {
  test.skip(!projectId || !referencePath, 'Requires isolated owned synthetic stereo state');
  test.setTimeout(120_000);
  const references = JSON.parse(await readFile(referencePath!, 'utf8')) as {
    kind: string;
    smiles: string;
    molfile: string;
  }[];
  const errors: string[] = [];
  page.on('pageerror', (error) => errors.push(error.message));
  await page.goto(`/#/projects/${projectId}`);
  await expect(page.getByRole('table')).toBeVisible();
  const observed: unknown[] = [];
  for (const [index, input] of references.entries()) {
    const id = `Compound ${index + 1}`;
    await page.getByLabel(`修正 ${id}`, { exact: true }).click();
    await expect(page.getByRole('button', { name: '保存修正', exact: true })).toBeEnabled();
    await page.evaluate(
      ({ channel, value }) => {
        const frame = document.querySelector<HTMLIFrameElement>(
          'iframe[title="Ketcher 结构绘制与预览"]',
        )!;
        const state = {
          loaded: false,
          drawing: null as { smiles: string; molfile: string } | null,
        };
        Object.assign(window, { __stereoReference: state });
        const receive = (event: MessageEvent) => {
          if (
            event.origin !== location.origin ||
            event.source !== frame.contentWindow ||
            event.data?.channel !== channel
          )
            return;
          if (event.data.kind === 'loaded') state.loaded = true;
          if (event.data.kind === 'change') state.drawing = event.data.value;
        };
        window.addEventListener('message', receive);
        frame.contentWindow!.postMessage(
          { channel, kind: 'load', smiles: value.smiles, molfile: value.molfile },
          location.origin,
        );
      },
      { channel: EDITOR_CHANNEL, value: input },
    );
    await expect
      .poll(() =>
        page.evaluate(
          () =>
            (window as unknown as { __stereoReference: { loaded: boolean } }).__stereoReference
              .loaded,
        ),
      )
      .toBe(true);
    const frame = page.frameLocator('iframe[title="Ketcher 结构绘制与预览"]');
    await frame.getByRole('button', { name: 'Clean Up (Ctrl+Shift+L)', exact: true }).click();
    await expect
      .poll(() =>
        page.evaluate(
          () =>
            (window as unknown as { __stereoReference: { drawing: unknown } }).__stereoReference
              .drawing,
        ),
      )
      .not.toBeNull();
    await expect(page.getByRole('button', { name: '保存修正', exact: true })).toBeEnabled();
    await page
      .getByRole('dialog')
      .screenshot({ path: test.info().outputPath(`native-${input.kind}.png`) });
    await page.getByRole('button', { name: '保存修正', exact: true }).click();
    await expect(page.getByRole('dialog')).toHaveCount(0);
    const correctionDocument = await (
      await page.request.get(
        `/api/v1/projects/${projectId}/structures/${encodeURIComponent(id)}/correction`,
      )
    ).json();
    expect(correctionDocument.values.structure_molfile).toContain('V3000');
    expect(correctionDocument.values.structure_molfile).toContain('CFG=2');
    const row = (
      await (
        await page.request.get(`/api/v1/projects/${projectId}/results?page=1&page_size=25`)
      ).json()
    ).items.find((item: { id: string }) => item.id === id);
    expect(row.structure_molfile).toBe(correctionDocument.values.structure_molfile);
    const image = await page.request.get(row.redraw_image_url);
    expect(image.status()).toBe(200);
    expect(image.headers()['content-type']).toContain('image/png');
    await writeFile(test.info().outputPath(`redraw-${input.kind}.png`), await image.body());
    await page.getByLabel(`修正 ${id}`, { exact: true }).click();
    await expect(page.getByRole('button', { name: '保存修正', exact: true })).toBeEnabled();
    await page
      .getByRole('dialog')
      .screenshot({ path: test.info().outputPath(`reopened-${input.kind}.png`) });
    await page.getByRole('button', { name: '取消', exact: true }).click();
    observed.push({ kind: input.kind, id, document: correctionDocument, row });
  }
  const session = await (await page.request.get('/api/v1/session')).json();
  for (const format of ['json', 'csv']) {
    const exported = await page.request.post(`/api/v1/projects/${projectId}/export`, {
      headers: { Origin: new URL(page.url()).origin, 'X-CSRF-Token': session.csrf_token },
      data: { format, compound_ids: [] },
    });
    expect(exported.status()).toBe(200);
    const body = await exported.text();
    expect(body).toContain('V3000');
    expect(body).toContain('CFG=2');
    await writeFile(test.info().outputPath(`stereo-export.${format}`), body);
  }
  const jobs = await (await page.request.get('/api/v1/jobs')).json();
  expect(jobs.items).toEqual([]);
  expect(errors).toEqual([]);
  await writeFile(
    test.info().outputPath('saved-native-stereo.json'),
    JSON.stringify(observed, null, 2),
  );
});
