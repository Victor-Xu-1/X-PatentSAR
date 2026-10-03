import { Copy } from 'lucide-react';
import { useState } from 'react';
import type { Compound } from '../../api/types';
import type { ResultColumn } from '../../model/resultColumns';
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
  const [fallback, setFallback] = useState<{ text: string; title: string } | null>(null);
  const [message, setMessage] = useState('');
  const [busy, setBusy] = useState(false);
  const checked = rows.filter((row) => selected.has(row.id));
  const scope = checked.length ? '当前页所选行' : '当前页';
  async function copy() {
    const copying = checked.length ? checked : rows;
    const text = tableCopyText(copying, columns, activities);
    const title = `复制${scope}`;
    setBusy(true);
    setMessage('');
    try {
      if (!navigator.clipboard?.writeText) throw new Error('Clipboard unavailable');
      await navigator.clipboard.writeText(text);
      setMessage(`已复制${scope} ${copying.length} 行（可见列）`);
    } catch {
      setFallback({ text, title });
    } finally {
      setBusy(false);
    }
  }
  return (
    <>
      <button
        type="button"
        className="toolbar-button"
        aria-label={`复制${scope}${checked.length ? ` (${checked.length})` : ''}`}
        title={`仅复制${scope}的可见列；全项目请用导出`}
        disabled={
          disabled || busy || !rows.length || !columns.some((column) => column.id !== 'select')
        }
        onClick={() => void copy()}
      >
        <Copy size={14} />
      </button>
      <output className="sr-only" aria-live="polite">
        {message}
      </output>
      {fallback && (
        <Dialog title={fallback.title} onClose={() => setFallback(null)}>
          <div className="dialog-body table-copy-fallback">
            <p>浏览器未授权剪贴板。仅当前页、可见列；在下方按 Ctrl+A、Ctrl+C，再粘贴到 Excel。</p>
            <textarea
              aria-label="可手动复制的 TSV"
              data-initial-focus
              value={fallback.text}
              readOnly
              onFocus={(event) => event.target.select()}
            />
            <small className="muted">
              多次观察以 | 分隔；结构列复制现有 SMILES / 原图状态。公式前缀已转义；原始数据未改变。
            </small>
          </div>
        </Dialog>
      )}
    </>
  );
}
