import { useTranslation } from '../../../i18n';
export function GroupPager({
  page,
  total,
  onPage,
  size = 12,
}: {
  page: number;
  total: number;
  onPage: (page: number) => void;
  size?: number;
}) {
  const { t } = useTranslation(),
    pages = Math.max(1, Math.ceil(total / size));
  if (pages === 1) return null;
  return (
    <div className="sar-pagination">
      <button type="button" disabled={page <= 1} onClick={() => onPage(page - 1)}>
        {t('上一页')}
      </button>
      <span>
        {page}/{pages}
      </span>
      <button type="button" disabled={page >= pages} onClick={() => onPage(page + 1)}>
        {t('下一页')}
      </button>
    </div>
  );
}
