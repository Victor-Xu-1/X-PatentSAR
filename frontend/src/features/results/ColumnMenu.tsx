import { useTranslation } from '../../i18n';
import { isLanguageSelection } from '../../i18n/interaction';
import { ArrowDown, ArrowUp, ChevronDown, EyeOff, Filter } from 'lucide-react';
import { useEffect, useId, useRef, useState } from 'react';
import { createPortal } from 'react-dom';
import type { ActivityColumn, Filters } from '../../api/types';
import type { ResultColumn } from '../../model/resultColumns';
import { columnCanFilter, columnCanSort, replaceColumnFilters } from '../../model/columnFilters';
import { ColumnFilterForm } from './ColumnFilterForm';
import { containTab } from '../../components/focus';

const COLUMN_MENU_MAX_HEIGHT = 550;

export function ColumnMenu({
  projectId,
  column,
  activity,
  filters,
  disabled = false,
  onFilters,
  onHide,
}: {
  projectId?: string | undefined;
  column: ResultColumn;
  activity?: ActivityColumn | undefined;
  filters?: Filters | undefined;
  disabled?: boolean;
  onFilters?: ((patch: Partial<Filters>) => void) | undefined;
  onHide: () => void;
}) {
  const { t } = useTranslation();
  const [position, setPosition] = useState<{ top: number; left: number } | null>(null);
  const button = useRef<HTMLButtonElement>(null);
  const panel = useRef<HTMLDialogElement>(null);
  const id = useId();
  const name = [column.label, column.context].filter(Boolean).join(' · ');
  const ownFilters = filters?.column_filters ?? [];
  const filtered = ownFilters.some((filter) => filter.column === column.id);
  const sorted = filters?.sort_column === column.id;
  const sortable = onFilters && columnCanSort(column);
  function close() {
    setPosition(null);
    button.current?.focus();
  }
  useEffect(() => {
    if (!position) return;
    panel.current
      ?.querySelector<HTMLElement>('button:not(:disabled),select:not(:disabled)')
      ?.focus();
    function outside(event: PointerEvent) {
      if (isLanguageSelection(event.target)) return;
      if (
        event.target instanceof Node &&
        !panel.current?.contains(event.target) &&
        !button.current?.contains(event.target)
      ) {
        setPosition(null);
        button.current?.focus();
      }
    }
    function escape(event: KeyboardEvent) {
      if (isLanguageSelection(event.target)) return;
      containTab(event, panel.current);
      if (event.key === 'Escape') {
        event.preventDefault();
        setPosition(null);
        button.current?.focus();
      }
    }
    function resize() {
      setPosition(null);
      button.current?.focus();
    }
    document.addEventListener('pointerdown', outside);
    document.addEventListener('keydown', escape);
    window.addEventListener('resize', resize);
    return () => {
      document.removeEventListener('pointerdown', outside);
      document.removeEventListener('keydown', escape);
      window.removeEventListener('resize', resize);
    };
  }, [position]);
  return (
    <>
      <button
        ref={button}
        type="button"
        className={`column-menu-button${filtered || sorted ? ' column-menu-active' : ''}`}
        aria-label={t('{name} 列选项', { name })}
        aria-haspopup="dialog"
        aria-expanded={Boolean(position)}
        aria-controls={position ? id : undefined}
        onClick={() => {
          if (position) {
            close();
            return;
          }
          const box = button.current!.getBoundingClientRect();
          // Filter content must reserve its own full preferred height. Brief
          // hide-only menus retain their existing placement.
          const reserve = onFilters && columnCanFilter(column) ? COLUMN_MENU_MAX_HEIGHT + 8 : 400;
          setPosition({
            left: Math.max(8, Math.min(box.right - 280, window.innerWidth - 288)),
            top: Math.max(8, Math.min(box.bottom + 4, window.innerHeight - reserve)),
          });
        }}
      >
        {filtered ? (
          <Filter size={12} />
        ) : sorted ? (
          filters?.sort_direction === 'desc' ? (
            <ArrowDown size={12} />
          ) : (
            <ArrowUp size={12} />
          )
        ) : (
          <ChevronDown size={12} />
        )}
      </button>
      {position &&
        createPortal(
          <dialog
            ref={panel}
            id={id}
            open
            aria-label={t('{name} 列选项', { name })}
            className="column-menu"
            style={{
              ...position,
              maxHeight: Math.min(COLUMN_MENU_MAX_HEIGHT, window.innerHeight - position.top - 8),
            }}
          >
            <strong>{column.label}</strong>
            {column.context && <small className="muted">{column.context}</small>}
            {onFilters && columnCanFilter(column) && (
              <button
                type="button"
                className="column-detail-toggle"
                disabled={disabled || !filtered}
                onClick={() => {
                  onFilters({
                    column_filters: ownFilters.filter((filter) => filter.column !== column.id),
                    page: 1,
                  });
                  close();
                }}
              >
                {t('清除此列筛选')}
              </button>
            )}
            {sortable && (
              <div className="column-sort-actions" aria-label={t('全项目排序')}>
                {(['asc', 'desc'] as const).map((direction) => (
                  <button
                    key={direction}
                    type="button"
                    aria-pressed={
                      sorted && !filters?.sort_band && filters?.sort_direction === direction
                    }
                    disabled={disabled}
                    onClick={() => {
                      onFilters({
                        sort_column: column.id,
                        sort_direction: direction,
                        sort_band: '',
                        page: 1,
                      });
                      close();
                    }}
                  >
                    {direction === 'asc' ? <ArrowUp size={12} /> : <ArrowDown size={12} />}
                    {direction === 'asc' ? t('升序') : t('降序')}
                  </button>
                ))}
                {sorted && (
                  <button
                    type="button"
                    disabled={disabled}
                    onClick={() => {
                      onFilters({ sort_column: '', sort_direction: 'asc', sort_band: '', page: 1 });
                      close();
                    }}
                  >
                    {t('取消排序')}
                  </button>
                )}
              </div>
            )}
            {onFilters && columnCanFilter(column) && (
              <ColumnFilterForm
                projectId={projectId}
                column={column}
                activity={activity}
                filters={
                  filters ?? {
                    q: '',
                    confidence: '',
                    review: '',
                    target: '',
                    page: 1,
                    page_size: 25,
                  }
                }
                disabled={disabled}
                onCancel={close}
                onSortBand={(band) => {
                  onFilters({
                    sort_column: column.id,
                    sort_direction: filters?.sort_direction ?? 'asc',
                    sort_band: band,
                    page: 1,
                  });
                  close();
                }}
                onApply={(replacement) => {
                  onFilters({
                    column_filters: replaceColumnFilters(ownFilters, column.id, replacement),
                    page: 1,
                  });
                  close();
                }}
              />
            )}
            <button
              type="button"
              className="column-hide"
              onClick={() => {
                close();
                onHide();
                document.querySelector<HTMLElement>('[data-column-chooser]')?.focus();
              }}
            >
              <EyeOff size={14} />
              {t('隐藏此列')}
            </button>
          </dialog>,
          document.body,
        )}
    </>
  );
}
