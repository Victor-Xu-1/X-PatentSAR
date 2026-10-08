import { useTranslation } from '../../i18n';
export function PageControls({
  page,
  total,
  onPage,
  disabled,
}: {
  page: number;
  total: number;
  onPage: (page: number) => void;
  disabled: boolean;
}) {
  const { t } = useTranslation();
  const pages = Math.max(1, Math.ceil(total / 50));
  return (
    <div className="sar-pagination">
      <button type="button" disabled={disabled || page <= 1} onClick={() => onPage(page - 1)}>
        {t('上一页')}
      </button>
      <span>{t('第 {page} / {pages} 页 · 共 {total} 行', { page, pages, total })}</span>
      <button type="button" disabled={disabled || page >= pages} onClick={() => onPage(page + 1)}>
        {t('下一页')}
      </button>
    </div>
  );
}
