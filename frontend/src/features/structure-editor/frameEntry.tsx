import { useEffect, useRef, useState } from 'react';
import { createRoot } from 'react-dom/client';
import { Editor } from 'ketcher-react';
import { StandaloneStructServiceProvider } from 'ketcher-standalone/dist/binaryWasmNoRender';
import type { Ketcher } from 'ketcher-core';
import { EDITOR_CHANNEL, readEditorLoad } from './protocol';
import type { EditorPayload } from './protocol';
import { captureDrawing, subscribeDrawing } from './subscribeDrawing';
import { boundedEditorOperation } from './structureConversion';
import { ApiError } from '../../api/errors';
import { UiError, useTranslation } from '../../i18n';
import { editorErrorSource } from './editorErrorSource';
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
  const { t } = useTranslation();
  const [provider] = useState(() => new StandaloneStructServiceProvider());
  const [instance, setInstance] = useState<Ketcher | null>(null);
  const [blocked, setBlocked] = useState(true);
  const [error, setError] = useState<Error | null>(null);
  const cleanup = useRef<(() => void) | null>(null);
  useEffect(() => {
    if (!instance) return;
    let disposed = false,
      loading = false;
    const lifetime = new AbortController();
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
          await boundedEditorOperation(
            () => instance.setMolecule(request.molfile ?? request.smiles),
            lifetime.signal,
          );
        // Canonicalize the loaded graph through the same MDL authority used for edits.
        // Supplied noncanonical SMILES must not make a coordinate-only edit look new.
        const original =
          request.molfile || request.smiles
            ? (await captureDrawing(instance, lifetime.signal)).graphKey
            : request.smiles;
        if (disposed) return;
        cleanup.current = subscribeDrawing(instance, original, send, editorErrorSource);
        setError(null);
        send({ kind: 'loaded' });
      } catch (failure) {
        if (disposed) return;
        const canRedraw = failure instanceof ApiError && failure.status === 422;
        if (canRedraw) cleanup.current = subscribeDrawing(instance, '', send, editorErrorSource);
        const error =
          failure instanceof Error
            ? failure
            : new UiError('当前结构无法加载或转换，请重新加载编辑器。原值不会自动清除。');
        setError(error);
        send({
          kind: 'error',
          message: error.message.slice(0, 1000),
          recoverable: canRedraw,
          ...editorErrorSource(error),
        });
      } finally {
        if (!disposed) setBlocked(false);
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
      lifetime.abort();
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
          const error = new UiError('绘图操作失败，请重新加载编辑器。');
          setError(error);
          send({ kind: 'error', message: error.message, source: error.source, recoverable: false });
        }}
      />
      {error && window.parent === window && (
        <p className="editor-frame-error" role="alert">
          {editorErrorSource(error).source
            ? t(editorErrorSource(error).source!, error instanceof UiError ? error.values : {})
            : error.message.slice(0, 1000)}
        </p>
      )}
    </div>
  );
}
const root = document.getElementById('ketcher-root');
if (!root) throw new Error('Structure editor root is absent');
createRoot(root).render(<KetcherFrame />);
