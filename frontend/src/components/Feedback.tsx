import { AlertCircle, Inbox, LoaderCircle, RefreshCw } from 'lucide-react';
import type { ReactNode } from 'react';
export function Loading({ label = '正在加载…' }: { label?: string }) {
  return (
    <output className="feedback loading">
      <LoaderCircle className="spin" size={22} />
      <span>{label}</span>
    </output>
  );
}
export function ErrorNotice({ error, onRetry }: { error: Error; onRetry?: () => void }) {
  return (
    <div className="error-notice" role="alert">
      <AlertCircle size={18} />
      <span>{error.message}</span>
      {onRetry && (
        <button type="button" onClick={onRetry}>
          <RefreshCw size={14} />
          重新加载
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
  return (
    <div className="feedback empty">
      <div className="empty-icon">
        <Inbox size={28} />
      </div>
      <h3>{title}</h3>
      <p>{description}</p>
      {action}
    </div>
  );
}
