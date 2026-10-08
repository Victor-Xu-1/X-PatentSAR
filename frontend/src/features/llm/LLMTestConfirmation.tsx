import { useTranslation } from '../../i18n';
import { Dialog } from '../../components/Dialog';

export function LLMTestConfirmation({
  busy,
  onClose,
  onConfirm,
}: {
  busy: boolean;
  onClose: () => void;
  onConfirm: () => void;
}) {
  const { t } = useTranslation();
  return (
    <Dialog title={t('确认接口测试')} busy={busy} onClose={onClose} className="llm-test-dialog">
      <div className="dialog-body">
        <p>{t('仅发送固定的合成文本，不含真实专利内容。可能产生 API 费用。')}</p>
        <p className="muted">{t('只测试已保存配置；不自动测试或重试。')}</p>
        <footer className="dialog-actions">
          <button type="button" data-initial-focus disabled={busy} onClick={onClose}>
            {t('取消测试')}
          </button>
          <button type="button" className="primary" disabled={busy} onClick={onConfirm}>
            {busy ? t('测试中…') : t('确认发送测试')}
          </button>
        </footer>
      </div>
    </Dialog>
  );
}
