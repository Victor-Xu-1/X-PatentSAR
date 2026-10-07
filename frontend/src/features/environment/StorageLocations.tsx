import { useId, useState } from 'react';
import type { ReactNode } from 'react';
import type { EnvironmentSettings, EnvironmentStorageLocations } from '../../api/environmentTypes';
import { ErrorNotice } from '../../components/Feedback';
import {
  normalizeStorageLocations,
  sameStorageLocations,
  storageLocationFields,
  storageLocations,
} from './storageLocations';

export function StorageLocations({
  settings,
  disabled,
  busy,
  requestError,
  children,
  onClose,
  onSave,
}: {
  settings: EnvironmentSettings;
  disabled: boolean;
  busy: boolean;
  requestError: Error | null;
  children?: ReactNode;
  onClose: () => void;
  onSave: (
    locations: EnvironmentStorageLocations,
    revision: number,
  ) => Promise<EnvironmentSettings | null>;
}) {
  const [base, setBase] = useState(settings);
  const [draft, setDraft] = useState(() => storageLocations(settings));
  const [seen, setSeen] = useState(settings.revision);
  const [error, setError] = useState<Error | null>(null);
  const noteId = useId();
  const dirty = !sameStorageLocations(draft, base);
  if (seen !== settings.revision) {
    setSeen(settings.revision);
    if (!dirty || sameStorageLocations(draft, settings)) {
      setBase(settings);
      setDraft(storageLocations(settings));
    }
  }
  const conflict = base.revision !== settings.revision;
  const locked = disabled || busy;
  return (
    <form
      className="dialog-body environment-storage-form"
      onSubmit={(event) => {
        event.preventDefault();
        if (locked || conflict || !dirty) return;
        setError(null);
        void (async () => {
          try {
            const locations = normalizeStorageLocations(draft, settings);
            const saved = await onSave(locations, base.revision);
            if (saved) onClose();
          } catch (caught) {
            setError(caught instanceof Error ? caught : new Error('存储位置保存失败。'));
          }
        })();
      }}
    >
      <p id={noteId} className="muted">
        仅影响后续写入，不会移动已有文件。生成结果含提取产物及 CSV/JSON
        导出副本；下载位置仍由浏览器设置。
      </p>
      <fieldset className="environment-storage-fields">
        <legend className="sr-only">存储目录</legend>
        {storageLocationFields.map(({ key, label, allowed }, index) => (
          <label className="form-field" key={key}>
            {label}
            <input
              value={draft[key]}
              maxLength={512}
              spellCheck={false}
              autoComplete="off"
              required
              disabled={locked}
              data-initial-focus={index === 0 ? true : undefined}
              aria-describedby={noteId}
              title={`允许范围：${settings[allowed]}`}
              onChange={(event) => setDraft({ ...draft, [key]: event.target.value })}
            />
          </label>
        ))}
      </fieldset>
      {conflict && (
        <div className="conflict">
          服务器配置已更新，未覆盖你的输入。当前存储位置：
          <ul className="break-word">
            {storageLocationFields.map(({ key, label }) => (
              <li key={key}>
                {label}：{settings[key]}
              </li>
            ))}
          </ul>
          <button type="button" onClick={() => setBase(settings)} disabled={locked}>
            使用最新版本并保留输入
          </button>
        </div>
      )}
      {(error || requestError) && <ErrorNotice error={error ?? requestError!} />}
      {children}
      <footer className="dialog-actions">
        <button type="button" onClick={onClose} disabled={busy}>
          取消
        </button>
        <button type="submit" className="primary" disabled={locked || conflict || !dirty}>
          {busy ? '保存中…' : '保存'}
        </button>
      </footer>
    </form>
  );
}
