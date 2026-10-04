import { useEffect, useRef, useState } from 'react';
import type { StructureChange } from './correctionDraft';
import { EDITOR_CHANNEL, readEditorMessage } from '../structure-editor/protocol';

export default function StructureEditor({
  smiles,
  molfile,
  disabled,
  onChange,
  onReady,
  onSave,
}: {
  smiles: string;
  molfile: string | null;
  disabled: boolean;
  onChange: (value: StructureChange) => void;
  onReady: (ready: boolean) => void;
  onSave: () => void;
}) {
  const frame = useRef<HTMLIFrameElement>(null);
  const initial = useRef({ smiles, molfile });
  const callbacks = useRef({ onChange, onReady, onSave });
  const [error, setError] = useState('');
  const [loaded, setLoaded] = useState(false);
  const [attempt, retry] = useState(0);
  useEffect(() => {
    callbacks.current = { onChange, onReady, onSave };
  }, [onChange, onReady, onSave]);
  useEffect(() => {
    let initialized = false;
    const timer = setTimeout(() => {
      if (!initialized) setError('结构编辑器加载超时，请重试。');
    }, 20000);
    const receive = (event: MessageEvent) => {
      if (event.origin !== window.location.origin || event.source !== frame.current?.contentWindow)
        return;
      try {
        const message = readEditorMessage(event.data);
        if (message.kind === 'ready') {
          frame.current?.contentWindow?.postMessage(
            { channel: EDITOR_CHANNEL, kind: 'load', ...initial.current },
            window.location.origin,
          );
        } else if (message.kind === 'loaded') {
          initialized = true;
          clearTimeout(timer);
          setLoaded(true);
          setError((current) => (current === '结构编辑器加载超时，请重试。' ? '' : current));
          callbacks.current.onReady(true);
        } else if (message.kind === 'save') callbacks.current.onSave();
        else if (message.kind === 'busy') callbacks.current.onReady(false);
        else if (message.kind === 'change') {
          setLoaded(true);
          callbacks.current.onChange(message.value);
          callbacks.current.onReady(true);
          setError('');
        } else if (message.kind === 'error') {
          if (!message.recoverable) setLoaded(false);
          setError(message.message);
          callbacks.current.onReady(message.recoverable);
        }
      } catch (failure) {
        setError(failure instanceof Error ? failure.message : '结构编辑数据无效。');
        callbacks.current.onReady(false);
      }
    };
    const save = (event: KeyboardEvent) => {
      if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === 's') {
        event.preventDefault();
        callbacks.current.onSave();
      }
    };
    document.addEventListener('keydown', save);
    window.addEventListener('message', receive);
    return () => {
      clearTimeout(timer);
      window.removeEventListener('message', receive);
      document.removeEventListener('keydown', save);
    };
  }, [attempt]);
  return (
    <section className="structure-editor" aria-label="结构式编辑器">
      {!loaded && !error && <output className="structure-loading">正在加载 Ketcher…</output>}
      <div
        className="structure-drawing-host"
        aria-label="结构式绘制区域"
        aria-disabled={disabled || (!loaded && !!error)}
        inert={disabled || (!loaded && !!error)}
      >
        <iframe
          key={attempt}
          ref={frame}
          src="/ketcher.html"
          title="Ketcher 结构绘制与预览"
          sandbox="allow-scripts allow-same-origin"
          referrerPolicy="no-referrer"
        />
      </div>
      {error && (
        <p role="alert" className="error-notice">
          {error}
        </p>
      )}
      {!loaded && error && (
        <button
          type="button"
          disabled={disabled}
          onClick={() => {
            if (
              !window.confirm(
                '重新加载会保留最近成功解析的结构和各列草稿；无法导出的绘图改动需重画。继续？',
              )
            )
              return;
            initial.current = { smiles, molfile };
            setLoaded(false);
            callbacks.current.onReady(false);
            setError('');
            retry(attempt + 1);
          }}
        >
          重试编辑器
        </button>
      )}
    </section>
  );
}
