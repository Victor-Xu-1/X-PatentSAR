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
  total: number;
  disabled: boolean;
  onChange: (page: number, size: number) => void;
}) {
  const last = Math.max(1, Math.ceil(total / pageSize));
  const pages = Array.from(
    { length: Math.min(5, last) },
    (_, index) => Math.min(Math.max(1, page - 2), Math.max(1, last - 4)) + index,
  );
  return (
    <footer className="pagination">
      <span className="muted">
        共 {total} 个化合物
        {total > 0 && ` · ${(page - 1) * pageSize + 1}–${Math.min(page * pageSize, total)}`}
      </span>
      <nav aria-label="结果分页">
        <button
          type="button"
          className="icon-button"
          aria-label="上一页结果"
          disabled={disabled || page <= 1}
          onClick={() => onChange(page - 1, pageSize)}
        >
          <ChevronLeft size={16} />
        </button>
        {pages.map((n) => (
          <button
            type="button"
            key={n}
            aria-label={`结果第 ${n} 页`}
            aria-current={n === page ? 'page' : undefined}
            className={n === page ? 'page-button active' : 'page-button'}
            onClick={() => onChange(n, pageSize)}
            disabled={disabled}
          >
            {n}
          </button>
        ))}
        <button
          type="button"
          className="icon-button"
          aria-label="下一页结果"
          disabled={disabled || page >= last}
          onClick={() => onChange(page + 1, pageSize)}
        >
          <ChevronRight size={16} />
        </button>
        <select
          aria-label="每页化合物数量"
          value={pageSize}
          disabled={disabled}
          onChange={(e) => onChange(1, Number(e.target.value))}
        >
          {[10, 25, 50, 100].map((size) => (
            <option key={size} value={size}>
              {size} 条/页
            </option>
          ))}
        </select>
      </nav>
    </footer>
  );
}
