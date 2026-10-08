import { ApiError } from '../../api/errors';
import { ErrorNotice } from '../../components/Feedback';
import { UiError } from '../../i18n';
export function SARFailure({ error, onRetry }: { error: Error; onRetry?: () => void }) {
  const serverError = error instanceof ApiError && error.code.startsWith('sar_');
  return (
    <>
      <ErrorNotice
        error={
          serverError
            ? new UiError('SAR 请求失败（{code}）。请检查当前状态。', { code: error.code })
            : error
        }
        {...(onRetry ? { onRetry } : {})}
      />
      {serverError && (
        <div className="sar-error-details">
          <p>{error.source}</p>
        </div>
      )}
    </>
  );
}
