import { SARFailure } from './SARFailure';
import { useTranslation } from '../../i18n';
import type { useSARMutation } from './useSARMutation';

export function MutationNotice({
  mutation,
  disabled = false,
  showSuccess = true,
}: {
  mutation: ReturnType<typeof useSARMutation>;
  disabled?: boolean;
  showSuccess?: boolean;
}) {
  const { t } = useTranslation();
  return (
    <div aria-live="polite">
      {mutation.error && <SARFailure error={mutation.error} />}
      {mutation.uncertain && mutation.requestId && (
        <p>{t('请求身份：{id}', { id: mutation.requestId })}</p>
      )}
      {mutation.canRetry && (
        <button type="button" disabled={disabled || mutation.busy} onClick={mutation.retry}>
          {t('已核对服务器状态，使用同一请求身份重试')}
        </button>
      )}
      {showSuccess && mutation.success && <output>{t('SAR 操作已完成。')}</output>}
    </div>
  );
}
