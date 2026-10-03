import { useEffect, useRef } from 'react';
import type { Activity, Compound } from '../../api/types';
import { availableMetrics } from '../../model/results';
import type { ResultDensity } from '../../model/results';
import { resultColumns } from '../../model/resultColumns';
import { ResizeHandle } from '../../components/ResizeHandle';
import { ResultRow } from './ResultRow';
import { useColumnResize } from './useColumnResize';

export function ResultsTable({
  rows,
  offset,
  metrics,
  density = 'compact',
  selected,
  focusedId,
  onSelect,
  onSelectPage,
  onJump,
  onActivitySource,
  onCrop,
  onReview,
}: {
  rows: Compound[];
  offset: number;
  metrics?: string[];
  density?: ResultDensity;
  selected: Set<string>;
  focusedId: string | null;
  onSelect: (id: string) => void;
  onSelectPage: (checked: boolean) => void;
  onJump: (compound: Compound) => void;
  onActivitySource: (activity: Activity) => void;
  onCrop: (compound: Compound) => void;
  onReview: (compound: Compound) => void;
}) {
  const selectAll = useRef<HTMLInputElement>(null);
  const container = useRef<HTMLDivElement>(null);
  const table = useRef<HTMLTableElement>(null);
  const columns = metrics ?? availableMetrics([], rows);
  const headers = resultColumns();
  const resize = useColumnResize(headers, table);
  const all = rows.length > 0 && rows.every((row) => selected.has(row.id));
  const some = rows.some((row) => selected.has(row.id));
  useEffect(() => {
    if (selectAll.current) selectAll.current.indeterminate = some && !all;
  }, [some, all]);
  useEffect(() => {
    if (!focusedId) return;
    const element = Array.from(
      container.current?.querySelectorAll<HTMLElement>('[data-compound]') ?? [],
    ).find((row) => row.dataset.compound === focusedId);
    element?.scrollIntoView({ block: 'nearest', behavior: 'smooth' });
  }, [focusedId, rows]);
  return (
    <section
      className="table-scroll"
      ref={container}
      // A scrollable table region needs a keyboard focus target for native scrolling.
      // oxlint-disable-next-line jsx-a11y/no-noninteractive-tabindex
      tabIndex={0}
      aria-label="可横向滚动的化合物结果表格"
    >
      <table
        ref={table}
        className={`results-table${resize.resized ? ' columns-resized' : ''}`}
        data-density={density}
        style={
          resize.resized
            ? { width: resize.totalWidth, minWidth: 0, tableLayout: 'fixed' }
            : undefined
        }
      >
        <caption className="sr-only">
          结构、专利活性与六项计算指标。每个活性值保留独立来源；
          计算指标不等于专利实测。点击修正可编辑并保存。
        </caption>
        <colgroup>
          {headers.map((header) => (
            <col
              key={header.id}
              style={
                resize.resized ? { width: resize.widths[header.id] ?? header.width } : undefined
              }
            />
          ))}
        </colgroup>
        <thead>
          <tr>
            {headers.map((header) => (
              <th
                className={header.className}
                scope="col"
                key={header.id}
                data-column={header.id}
                aria-label={header.id === 'number' ? '#' : header.label}
              >
                {header.id === 'select' ? (
                  <input
                    ref={selectAll}
                    type="checkbox"
                    aria-label="选择当前页全部化合物"
                    checked={all}
                    onChange={(event) => onSelectPage(event.target.checked)}
                    disabled={!rows.length}
                  />
                ) : header.id === 'number' ? (
                  '#'
                ) : (
                  header.label
                )}
                <ResizeHandle
                  className="column-resizer"
                  label={`调整${header.label}列宽`}
                  value={resize.widths[header.id] ?? header.width}
                  min={header.min}
                  max={header.max}
                  resetValue={header.width}
                  onBegin={() => resize.begin(header.id)}
                  onPreview={(next) => resize.preview(header.id, next)}
                  onCommit={(next) => resize.commit(header.id, next)}
                />
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {rows.map((row, index) => (
            <ResultRow
              key={row.id}
              row={row}
              number={offset + index + 1}
              metrics={columns}
              selected={selected.has(row.id)}
              focused={focusedId === row.id}
              onSelect={() => onSelect(row.id)}
              onJump={onJump}
              onActivitySource={onActivitySource}
              onCrop={onCrop}
              onReview={onReview}
            />
          ))}
        </tbody>
      </table>
    </section>
  );
}
