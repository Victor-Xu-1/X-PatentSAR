import { useEffect, useRef, useState } from 'react';
import { createRoot } from 'react-dom/client';
import { Editor } from 'ketcher-react';
import { StandaloneStructServiceProvider } from 'ketcher-standalone/dist/binaryWasmNoRender';
import type { Ketcher } from 'ketcher-core';
import { EDITOR_CHANNEL, readEditorLoad } from './protocol';
import type { EditorPayload } from './protocol';
import { subscribeDrawing } from './subscribeDrawing';
import 'ketcher-react/dist/index.css';
import './frame.css';

const buttons = {
  miew: { hidden: true },
  analyse: { hidden: true },
  recognize: { hidden: true },
  help: { hidden: true },
  about: { hidden: true },
  settings: { hidden: true },
  fullscreen: { hidden: true },
  sgroup: { hidden: true },
  rgroup: { hidden: true },
  'reaction-plus': { hidden: true },
  arrows: { hidden: true },
  'reaction-mapping-tools': { hidden: true },
  shape: { hidden: true },
  text: { hidden: true },
  'create-monomer': { hidden: true },
  'enhanced-stereo': { hidden: true },
};
function send(message: EditorPayload) {
  window.parent.postMessage({ channel: EDITOR_CHANNEL, ...message }, window.location.origin);
}
function KetcherFrame() {
  const [provider] = useState(() => new StandaloneStructServiceProvider());
  const [instance, setInstance] = useState<Ketcher | null>(null);
  const [blocked, setBlocked] = useState(true);
  const [error, setError] = useState('');
  const cleanup = useRef<(() => void) | null>(null);
  useEffect(() => {
    if (!instance) return;
    let disposed = false,
      loading = false;
    const receive = async (event: MessageEvent) => {
      if (event.source !== window.parent || event.origin !== window.location.origin || loading)
        return;
      if (event.data?.channel !== EDITOR_CHANNEL) return;
      loading = true;
      cleanup.current?.();
      cleanup.current = null;
      setBlocked(true);
      try {
        const request = readEditorLoad(event.data);
        if (request.molfile || request.smiles)
          await instance.setMolecule(request.molfile ?? request.smiles);
        const original = (await instance.getSmiles()).trim();
        if (disposed) return;
        cleanup.current = subscribeDrawing(instance, original, send);
        setError('');
      } catch {
        if (disposed) return;
        // Preserve parent data. Only subsequent intentional drawing replaces it.
        cleanup.current = subscribeDrawing(instance, '', send);
        setError('当前结构无法加载，可清空后重画。原值不会自动清除。');
        send({ kind: 'error', message: '当前结构无法加载，可清空后重画。', recoverable: true });
      } finally {
        if (!disposed) {
          setBlocked(false);
          send({ kind: 'loaded' });
        }
        loading = false;
      }
    };
    const handler = (event: MessageEvent) => {
      void receive(event);
    };
    const save = (event: KeyboardEvent) => {
      if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === 's') {
        event.preventDefault();
        event.stopImmediatePropagation();
        send({ kind: 'save' });
      }
    };
    document.addEventListener('keydown', save, true);
    window.addEventListener('message', handler);
    send({ kind: 'ready' });
    return () => {
      disposed = true;
      window.removeEventListener('message', handler);
      document.removeEventListener('keydown', save, true);
      cleanup.current?.();
      cleanup.current = null;
    };
  }, [instance]);
  return (
    <div className="editor-frame-root" inert={blocked}>
      <Editor
        staticResourcesUrl="/"
        structServiceProvider={provider}
        disableMacromoleculesEditor
        buttons={buttons}
        onInit={setInstance}
        errorHandler={() => {
          setError('绘图操作失败，请检查结构后重试。');
        }}
      />
      {error && (
        <p className="editor-frame-error" role="alert">
          {error}
        </p>
      )}
    </div>
  );
}
const root = document.getElementById('ketcher-root');
if (!root) throw new Error('Structure editor root is absent');
createRoot(root).render(<KetcherFrame />);
