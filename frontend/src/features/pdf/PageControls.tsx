import { useState } from 'react';
import { ChevronLeft, ChevronRight, Minus, Plus, RotateCcw, Settings2 } from 'lucide-react';
import { Dialog } from '../../components/Dialog';
export function PageControls({
  page,
  total,
  zoom,
  disabled,
  onPage,
  onZoom,
}: {
  page: number | null;
  total: number;
  zoom: number;
  disabled: boolean;
  onPage: (page: number) => void;
  onZoom: (zoom: number) => void;
}) {
  const [input, setInput] = useState(page === null ? '' : String(page));
  const [toolsOpen, setToolsOpen] = useState(false);
  const valid = /^\d+$/.test(input) && Number(input) >= 1 && Number(input) <= total;
  return (
    <div className="pdf-controls">
      <div className="page-navigation">
        <button
          type="button"
          className="icon-button"
          aria-label="上一页原始文档"
          disabled={disabled || page === null || page <= 1}
          onClick={() => page !== null && onPage(page - 1)}
        >
          <ChevronLeft size={16} />
        </button>
        <form
          onSubmit={(event) => {
            event.preventDefault();
            if (valid && !disabled) onPage(Number(input));
          }}
        >
          <input
            type="text"
            inputMode="numeric"
            aria-label="原始文档页码"
            aria-invalid={input !== '' && !valid && !disabled}
            value={input}
            placeholder="—"
            onChange={(event) => setInput(event.target.value)}
            disabled={disabled}
            title={`输入 1–${total}，回车跳页`}
          />
          <span>/ {total || '—'}</span>
        </form>
        <button
          type="button"
          className="icon-button"
          aria-label="下一页原始文档"
          disabled={disabled || page === null || page >= total}
          onClick={() => page !== null && onPage(page + 1)}
        >
          <ChevronRight size={16} />
        </button>
      </div>
      <button
        type="button"
        className="toolbar-button"
        aria-label="文档工具"
        title="文档工具"
        disabled={disabled || page === null}
        onClick={() => setToolsOpen(true)}
      >
        <Settings2 size={14} />
      </button>
      {toolsOpen && (
        <Dialog title="文档工具" onClose={() => setToolsOpen(false)}>
          <div className="dialog-body zoom-controls">
            <button
              type="button"
              className="icon-button"
              aria-label="缩小原始文档"
              disabled={disabled || zoom <= 0.5}
              onClick={() => onZoom(Math.max(0.5, zoom - 0.25))}
            >
              <Minus size={15} />
            </button>
            <output aria-label="文档缩放比例" title="100% 表示适配当前栏宽；拖动栏宽时自动重新适配">
              {Math.round(zoom * 100)}%
            </output>
            <button
              type="button"
              className="icon-button"
              aria-label="放大原始文档"
              disabled={disabled || zoom >= 2}
              onClick={() => onZoom(Math.min(2, zoom + 0.25))}
            >
              <Plus size={15} />
            </button>
            <button
              type="button"
              className="icon-button"
              aria-label="重置文档缩放"
              title="恢复适配当前可用宽度（100%）"
              disabled={disabled || zoom === 1}
              onClick={() => onZoom(1)}
            >
              <RotateCcw size={15} />
            </button>
          </div>
        </Dialog>
      )}
    </div>
  );
}
