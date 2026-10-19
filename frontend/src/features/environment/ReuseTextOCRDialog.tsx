import { useId, useState } from 'react';
import type { ReactNode } from 'react';
import { Dialog } from '../../components/Dialog';
import { ErrorNotice } from '../../components/Feedback';
import { UiError, useTranslation } from '../../i18n';
import { decodeEnvironmentReuseSource } from '../../api/environmentDecoders';
import type { EnvironmentCatalog, EnvironmentReuseSource } from '../../api/environmentTypes';

export function ReuseTextOCRDialog({
  catalog,
  busy,
  disabled,
  error,
  recovery,
  onClose,
  onConfirm,
}: {
  catalog: EnvironmentCatalog;
  busy: boolean;
  disabled: boolean;
  error: Error | null;
  recovery: ReactNode;
  onClose: () => void;
  onConfirm: (source: EnvironmentReuseSource, revision: number) => Promise<void>;
}) {
  const { t } = useTranslation();
  const [revision] = useState(catalog.settings.revision);
  const [source, setSource] = useState({
    python: catalog.components.find((item) => item.id === 'text-ocr')?.location ?? '',
    models: catalog.components.find((item) => item.id === 'text-ocr-models')?.location ?? '',
  });
  const [confirmed, setConfirmed] = useState(false);
  const [localError, setLocalError] = useState<Error | null>(null);
  const note = useId(),
    stale = revision !== catalog.settings.revision;
  return (
    <Dialog title={t('复用现有文字 OCR')} busy={busy} onClose={onClose}>
      <form
        className="dialog-body environment-reuse-form"
        onSubmit={(event) => {
          event.preventDefault();
          if (disabled || stale || !confirmed) return;
          setLocalError(null);
          try {
            const selected = decodeEnvironmentReuseSource(source);
            void onConfirm(selected, revision);
          } catch {
            setLocalError(
              new UiError('请填写有效的 Linux 解释器和本地权重目录，不接受命令或路径跳转。'),
            );
          }
        }}
      >
        <p id={note} className="muted">
          {t(
            '仅验证现有环境并复制固定权重到受管目录；不下载、不安装依赖。失败即停止，全部通过才按需启用。',
          )}
        </p>
        {(['python', 'models'] as const).map((key, index) => (
          <label className="form-field" key={key}>
            {t(key === 'python' ? '现有 Linux Python 解释器' : '现有权重目录')}
            <input
              data-initial-focus={index === 0 ? true : undefined}
              value={source[key]}
              required
              maxLength={512}
              spellCheck={false}
              autoComplete="off"
              disabled={disabled || stale}
              aria-describedby={note}
              onChange={(event) => setSource({ ...source, [key]: event.target.value })}
            />
          </label>
        ))}
        <label className="option-check">
          <input
            type="checkbox"
            checked={confirmed}
            disabled={disabled || stale}
            onChange={(event) => setConfirmed(event.target.checked)}
          />
          {t('允许本地复制权重并在验证通过后按需启用')}
        </label>
        {stale && <p role="alert">{t('环境配置已变化，请关闭后重新确认。')}</p>}
        {(localError || error) && <ErrorNotice error={localError ?? error!} />}
        {recovery}
        <footer className="dialog-actions">
          <button type="button" onClick={onClose} disabled={busy}>
            {t('取消')}
          </button>
          <button
            type="submit"
            className="primary"
            disabled={disabled || stale || !confirmed || !source.python || !source.models}
          >
            {busy ? t('验证中…') : t('验证并复用')}
          </button>
        </footer>
      </form>
    </Dialog>
  );
}
