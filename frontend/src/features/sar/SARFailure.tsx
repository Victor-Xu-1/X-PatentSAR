import { ApiError } from '../../api/errors';
import { ErrorNotice } from '../../components/Feedback';
import { errorText, UiError, useTranslation } from '../../i18n';
export function SARFailure({
  error,
  onRetry,
  requestId,
}: {
  error: Error;
  onRetry?: () => void;
  requestId?: string | null;
}) {
  const { t } = useTranslation();
  const serverError = error instanceof ApiError && error.code.startsWith('sar_');
  return (
    <>
      <ErrorNotice
        error={
          serverError && !error.uncertain
            ? new UiError(onRetry ? '无法读取 SAR 数据。' : 'SAR 操作失败。')
            : error
        }
        {...(onRetry ? { onRetry } : {})}
      />
      {(serverError || requestId) && (
        <details className="sar-error-details">
          <summary>{t('错误详情')}</summary>
          <p>{errorText(error)}</p>
          {error instanceof ApiError && <code>{error.code}</code>}
          {requestId && <p>{t('请求身份：{id}', { id: requestId })}</p>}
        </details>
      )}
    </>
  );
}
