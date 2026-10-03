import { useEffect, useRef } from 'react';
import type { ActivityColumn, Compound } from '../../api/types';
import type { CSSProperties } from 'react';
import { availableMetrics } from '../../model/results';
import type { ResultDensity } from '../../model/results';
import { resultColumns } from '../../model/resultColumns';
import { tableActivityColumns } from '../../model/activityColumns';
import type { ActivitySourceCallback } from '../../model/activityColumns';
import { ResizeHandle } from '../../components/ResizeHandle';
import { ResultRow } from './ResultRow';
import { useColumnResize } from './useColumnResize';

export function ResultsTable({
  rows,
  metrics,
  activityColumns,
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
  metrics?: string[];
  activityColumns?: ActivityColumn[];
  density?: ResultDensity;
  selected: Set<string>;
  focusedId: string | null;
  onSelect: (id: string) => void;
  onSelectPage: (checked: boolean) => void;
  onJump: (compound: Compound) => void;
  onActivitySource: ActivitySourceCallback;
  onCrop: (compound: Compound) => void;
  onReview: (compound: Compound) => void;
}) {
  const selectAll = useRef<HTMLInputElement>(null);
  const container = useRef<HTMLDivElement>(null);
  const table = useRef<HTMLTableElement>(null);
  const names =
    metrics ?? availableMetrics(activityColumns?.map((column) => column.name) ?? [], rows);
  const columns = tableActivityColumns(activityColumns, names);
  const headers = resultColumns(columns);
  const resize = useColumnResize(headers, table);
  const widthFor = (id: string) =>
    resize.widths[id] ?? headers.find((header) => header.id === id)!.width;
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
      style={
        {
          '--frozen-select-width': `${widthFor('select')}px`,
          '--frozen-compound-width': `${widthFor('compound')}px`,
          '--frozen-leading-width': `${widthFor('select') + widthFor('compound') + widthFor('structure')}px`,
          '--frozen-trailing-width': `${widthFor('edit')}px`,
        } as CSSProperties
      }
    >
      <table
        ref={table}
        className={`results-table${resize.resized ? ' columns-resized' : ''}`}
        data-density={density}
        style={
          {
            width: resize.totalWidth,
            minWidth: 0,
            tableLayout: 'fixed',
          } as CSSProperties
        }
      >
        <caption className="sr-only">
          Compound
          编号与结构独立成列。每种活性与实验独立成列，六项计算指标独立成列。每个活性值保留独立来源；
          计算指标不等于专利实测。点击修正可编辑并保存。
        </caption>
        <colgroup>
          {headers.map((header) => (
            <col key={header.id} style={{ width: resize.widths[header.id] ?? header.width }} />
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
                aria-label={[header.label, header.context].filter(Boolean).join(' · ')}
                title={[header.label, header.context].filter(Boolean).join(' · ')}
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
                ) : (
                  <span className="column-heading">
                    <span>{header.label}</span>
                    {header.details && <small>{header.details}</small>}
                  </span>
                )}
                <ResizeHandle
                  className="column-resizer"
                  label={`调整${[header.label, header.context].filter(Boolean).join(' · ')}列宽`}
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
          {rows.map((row) => (
            <ResultRow
              key={row.id}
              row={row}
              columns={columns}
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
