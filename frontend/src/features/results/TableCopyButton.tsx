import { useTranslation } from '../../i18n';
import { Copy } from 'lucide-react';
import { useState } from 'react';
import type { Compound } from '../../api/types';
import type { ResultColumn } from '../../model/resultColumns';
import { resultColumns } from '../../model/resultColumns';
import type { TableActivityColumn } from '../../model/activityColumns';
import { tableCopyText } from '../../model/tableCopy';
import { Dialog } from '../../components/Dialog';

export function TableCopyButton({
  rows,
  selected,
  columns,
  activities,
  disabled,
}: {
  rows: Compound[];
  selected: ReadonlySet<string>;
  columns: ResultColumn[];
  activities: TableActivityColumn[];
  disabled: boolean;
}) {
  const { t } = useTranslation();
  const [fallback, setFallback] = useState<{
    rows: Compound[];
    columnIds: string[];
    activities: TableActivityColumn[];
    selected: boolean;
  } | null>(null);
  const [message, setMessage] = useState<{ selected: boolean; count: number } | null>(null);
  const [busy, setBusy] = useState(false);
  const checked = rows.filter((row) => selected.has(row.id));
  const scope = checked.length ? t('当前页所选行') : t('当前页');
  async function copy() {
    const copying = checked.length ? checked : rows;
    const text = tableCopyText(copying, columns, activities);
    const selected = checked.length > 0;
    setBusy(true);
    setMessage(null);
    try {
      if (!navigator.clipboard?.writeText) throw new Error('Clipboard unavailable');
      await navigator.clipboard.writeText(text);
      setMessage({ selected, count: copying.length });
    } catch {
      setFallback({
        rows: copying,
        columnIds: columns.map((column) => column.id),
        activities,
        selected,
      });
    } finally {
      setBusy(false);
    }
  }
  return (
    <>
      <button
        type="button"
        className="toolbar-button"
        aria-label={t('复制{scope}{count}', {
          scope,
          count: checked.length ? ` (${checked.length})` : '',
        })}
        title={t('仅复制{scope}的可见列；全项目请用导出', { scope })}
        disabled={
          disabled || busy || !rows.length || !columns.some((column) => column.id !== 'select')
        }
        onClick={() => void copy()}
      >
        <Copy size={14} />
      </button>
      <output className="sr-only" aria-live="polite">
        {message &&
          t('已复制{scope} {count} 行（可见列）', {
            scope: t(message.selected ? '当前页所选行' : '当前页'),
            count: message.count,
          })}
      </output>
      {fallback && (
        <Dialog
          title={t('复制{scope}', { scope: t(fallback.selected ? '当前页所选行' : '当前页') })}
          onClose={() => setFallback(null)}
        >
          <div className="dialog-body table-copy-fallback">
            <p>
              {t('浏览器未授权剪贴板。仅当前页、可见列；在下方按 Ctrl+A、Ctrl+C，再粘贴到 Excel。')}
            </p>
            <textarea
              aria-label={t('可手动复制的 TSV')}
              data-initial-focus
              value={tableCopyText(
                fallback.rows,
                resultColumns(fallback.activities).filter((column) =>
                  fallback.columnIds.includes(column.id),
                ),
                fallback.activities,
              )}
              readOnly
              onFocus={(event) => event.target.select()}
            />
            <small className="muted">
              {t(
                '多次观察以 | 分隔；结构列复制现有 SMILES / 原图状态。公式前缀已转义；原始数据未改变。',
              )}
            </small>
          </div>
        </Dialog>
      )}
    </>
  );
}
