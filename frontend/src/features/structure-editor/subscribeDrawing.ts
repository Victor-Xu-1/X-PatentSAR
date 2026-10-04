import type { Ketcher } from 'ketcher-core';
import type { EditorPayload } from './protocol';
import { boundedEditorOperation, convertMolfile } from './structureConversion';
import { ApiError } from '../../api/errors';

/** One native MDL export; the backend alone decides chemistry and empty drawings. */
export async function captureDrawing(ketcher: Ketcher, signal: AbortSignal) {
  if (ketcher.containsReaction()) throw new Error('请绘制分子结构，不使用反应箭头。');
  const rawMolfile = await boundedEditorOperation(() => ketcher.getMolfile('v3000'), signal);
  const smiles = await convertMolfile(rawMolfile, signal);
  return {
    smiles: smiles ?? '',
    molfile: smiles === null ? null : rawMolfile,
    graphKey: smiles ?? '',
  };
}

/** One in-flight export and a short latest-change debounce, never a polling loop. */
export function subscribeDrawing(
  ketcher: Ketcher,
  originalKey: string,
  send: (message: EditorPayload) => void,
) {
  let version = 0,
    active = false,
    disposed = false;
  let timer: ReturnType<typeof setTimeout> | undefined;
  const lifetime = new AbortController();
  async function capture() {
    if (active || disposed) return;
    active = true;
    const current = version;
    try {
      const drawing = await captureDrawing(ketcher, lifetime.signal);
      if (disposed || current !== version) return;
      send({
        kind: 'change',
        value: {
          ...drawing,
          graphChanged: drawing.graphKey !== originalKey,
        },
      });
    } catch (failure) {
      if (!disposed && current === version)
        send({
          kind: 'error',
          recoverable: failure instanceof ApiError && failure.status === 422,
          message:
            failure instanceof Error
              ? failure.message.slice(0, 1000)
              : '结构无法导出，请修正后重试。',
        });
    } finally {
      active = false;
      if (!disposed && current !== version) schedule();
    }
  }
  function schedule() {
    clearTimeout(timer);
    timer = setTimeout(() => {
      void capture();
    }, 90);
  }
  const subscription = ketcher.editor.subscribe('change', () => {
    version += 1;
    send({ kind: 'busy' });
    schedule();
  });
  return () => {
    disposed = true;
    clearTimeout(timer);
    lifetime.abort();
    ketcher.editor.unsubscribe('change', subscription);
  };
}
