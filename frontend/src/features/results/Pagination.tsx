import { useTranslation } from '../../i18n';
import { ChevronLeft, ChevronRight } from 'lucide-react';
export function Pagination({
  page,
  pageSize,
  total,
  disabled,
  onChange,
}: {
  page: number;
  pageSize: number;
  total: number | null;
  disabled: boolean;
  onChange: (page: number, size: number) => void;
}) {
  const { t } = useTranslation();
  const unavailable = disabled || total === null;
  const last = total === null ? 1 : Math.max(1, Math.ceil(total / pageSize));
  const pages = Array.from(
    { length: Math.min(5, last) },
    (_, index) => Math.min(Math.max(1, page - 2), Math.max(1, last - 4)) + index,
  );
  return (
    <footer className="pagination">
      <span className="muted">
        {total === null ? t('记录数未知') : t('共 {total} 条记录', { total })}
        {total !== null &&
          total > 0 &&
          ` · ${(page - 1) * pageSize + 1}–${Math.min(page * pageSize, total)}`}
      </span>
      <nav aria-label={t('结果分页')}>
        <button
          type="button"
          className="icon-button"
          aria-label={t('上一页结果')}
          disabled={unavailable || page <= 1}
          onClick={() => onChange(page - 1, pageSize)}
        >
          <ChevronLeft size={16} />
        </button>
        {pages.map((n) => (
          <button
            type="button"
            key={n}
            aria-label={t('结果第 {page} 页', { page: n })}
            aria-current={n === page ? 'page' : undefined}
            className={n === page ? 'page-button active' : 'page-button'}
            onClick={() => onChange(n, pageSize)}
            disabled={unavailable}
          >
            {n}
          </button>
        ))}
        <button
          type="button"
          className="icon-button"
          aria-label={t('下一页结果')}
          disabled={unavailable || page >= last}
          onClick={() => onChange(page + 1, pageSize)}
        >
          <ChevronRight size={16} />
        </button>
        <select
          aria-label={t('每页记录数量')}
          value={pageSize}
          disabled={unavailable}
          onChange={(e) => onChange(1, Number(e.target.value))}
        >
          {[10, 25, 50, 100].map((size) => (
            <option key={size} value={size}>
              {t('{size} 条/页', { size })}
            </option>
          ))}
        </select>
      </nav>
    </footer>
  );
}
