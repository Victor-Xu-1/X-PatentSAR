import { useEffect, useRef } from 'react';
import type { Activity, Compound } from '../../api/types';
import { availableMetrics } from '../../model/results';
import type { ResultDensity } from '../../model/results';
import { ResultRow } from './ResultRow';

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
  const columns = metrics ?? availableMetrics([], rows);
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
      <table className="results-table" data-density={density}>
        <caption className="sr-only">
          真实指标独立成列；实验编号对应去重上下文，每个活性值保留自己的来源页。
          绑定证据、识别校验和人工复核是独立状态。
        </caption>
        <thead>
          <tr>
            <th className="check-col">
              <input
                ref={selectAll}
                type="checkbox"
                aria-label="选择当前页全部化合物"
                checked={all}
                onChange={(event) => onSelectPage(event.target.checked)}
                disabled={!rows.length}
              />
            </th>
            <th className="number-column">#</th>
            <th className="structure-column">原始结构 / 编号</th>
            <th className="context-column">靶点 / 实验</th>
            {columns.map((metric) => (
              <th className="activity-column" key={metric} scope="col">
                {metric || '未命名指标'}
              </th>
            ))}
            <th className="evidence-column">绑定证据</th>
            <th className="recognition-column">识别校验</th>
            <th className="source-column">结构来源</th>
            <th className="review-column">人工复核</th>
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
