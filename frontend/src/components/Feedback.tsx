import { AlertCircle, Inbox, LoaderCircle, RefreshCw } from 'lucide-react';
import type { ReactNode } from 'react';
import { errorText, useTranslation } from '../i18n';
export function Loading({ label = '正在加载…' }: { label?: string }) {
  const { t } = useTranslation();
  return (
    <output className="feedback loading">
      <LoaderCircle className="spin" size={22} />
      <span>{t(label)}</span>
    </output>
  );
}
export function ErrorNotice({ error, onRetry }: { error: Error; onRetry?: () => void }) {
  const { t } = useTranslation();
  return (
    <div className="error-notice" role="alert">
      <AlertCircle size={18} />
      <span>{errorText(error)}</span>
      {onRetry && (
        <button type="button" onClick={onRetry}>
          <RefreshCw size={14} />
          {t('重新加载')}
        </button>
      )}
    </div>
  );
}
export function Empty({
  title,
  description,
  action,
}: {
  title: string;
  description: string;
  action?: ReactNode;
}) {
  const { t } = useTranslation();
  return (
    <div className="feedback empty">
      <div className="empty-icon">
        <Inbox size={28} />
      </div>
      <h3>{t(title)}</h3>
      <p>{t(description)}</p>
      {action}
    </div>
  );
}
