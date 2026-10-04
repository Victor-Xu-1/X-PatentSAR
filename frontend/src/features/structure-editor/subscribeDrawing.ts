import type { Ketcher } from 'ketcher-core';
import type { EditorPayload } from './protocol';

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
  async function bounded<T>(promise: Promise<T>): Promise<T> {
    let expiry: ReturnType<typeof setTimeout> | undefined;
    try {
      return await Promise.race([
        promise,
        new Promise<T>((_, reject) => {
          expiry = setTimeout(() => reject(new Error('绘图导出超时，请重新加载编辑器。')), 15000);
        }),
      ]);
    } finally {
      clearTimeout(expiry);
    }
  }
  async function capture() {
    if (active || disposed) return;
    active = true;
    const current = version;
    try {
      if (ketcher.containsReaction()) throw new Error('请绘制分子结构，不使用反应箭头。');
      // The standalone SDK identifies convert replies by input text only. Two
      // parallel formats for the same graph can resolve to the wrong format.
      const rawSmiles = await bounded(ketcher.getSmiles());
      const rawMolfile = await bounded(ketcher.getMolfile('v3000'));
      if (disposed || current !== version) return;
      const smiles = rawSmiles.trim();
      if (smiles.length > 2048 || rawMolfile.length > 131072)
        throw new Error('结构超过支持的编辑范围。');
      send({
        kind: 'change',
        value: {
          smiles,
          molfile: smiles ? rawMolfile : null,
          graphKey: smiles,
          graphChanged: smiles !== originalKey,
        },
      });
    } catch (failure) {
      if (!disposed && current === version)
        send({
          kind: 'error',
          recoverable: false,
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
    ketcher.editor.unsubscribe('change', subscription);
  };
}
