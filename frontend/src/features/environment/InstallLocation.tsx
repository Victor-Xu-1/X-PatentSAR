import { useState } from 'react';
import type { EnvironmentSettings } from '../../api/environmentTypes';
import { normalizeInstallRoot } from '../../model/environment';
import { ErrorNotice } from '../../components/Feedback';
export function InstallLocation({
  settings,
  disabled,
  onSave,
}: {
  settings: EnvironmentSettings;
  disabled: boolean;
  onSave: (root: string, revision: number) => Promise<EnvironmentSettings | null>;
}) {
  const [base, setBase] = useState(settings),
    [draft, setDraft] = useState(settings.install_root);
  const [seen, setSeen] = useState(settings.revision),
    [error, setError] = useState<Error | null>(null);
  if (seen !== settings.revision) {
    setSeen(settings.revision);
    if (draft === base.install_root) {
      setBase(settings);
      setDraft(settings.install_root);
    }
  }
  const conflict = base.revision !== settings.revision;
  return (
    <section className="panel environment-card location-card">
      <h2>安装位置</h2>
      <p className="muted">
        仅影响后续新安装，不迁移或删除现有环境。只接受批准的本地目录，不接受 C
        盘、UNC、网络路径或命令。
      </p>
      <form
        onSubmit={(e) => {
          e.preventDefault();
          setError(null);
          void (async () => {
            try {
              const root = normalizeInstallRoot(draft, settings.allowed_root);
              const saved = await onSave(root, base.revision);
              if (saved) {
                setBase(saved);
                setDraft(saved.install_root);
              }
            } catch (e) {
              setError(e instanceof Error ? e : new Error('安装位置保存失败。'));
            }
          })();
        }}
      >
        <label className="form-field">
          环境安装目录
          <input
            value={draft}
            maxLength={512}
            spellCheck={false}
            disabled={disabled}
            onChange={(e) => setDraft(e.target.value)}
          />
        </label>
        <small className="break-word muted">
          允许范围：{settings.allowed_root} · 配置版本 {settings.revision}
        </small>
        {conflict && (
          <div className="conflict">
            服务器配置已更新，未覆盖你的输入。当前目录：{settings.install_root}
            <button type="button" onClick={() => setBase(settings)} disabled={disabled}>
              使用最新版本并保留输入
            </button>
          </div>
        )}
        {error && <ErrorNotice error={error} />}
        <button type="submit" disabled={disabled || conflict || draft === base.install_root}>
          保存安装位置
        </button>
      </form>
    </section>
  );
}
