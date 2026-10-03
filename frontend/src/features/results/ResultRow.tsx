import { Pencil } from 'lucide-react';
import type { Activity, Compound } from '../../api/types';
import { ActivitySummary } from './ActivitySummary';
import { PredictionCells } from './PredictionCells';
import { StructureCell } from './StructureCell';

export function ResultRow({
  row,
  number,
  metrics,
  selected,
  focused,
  onSelect,
  onJump,
  onActivitySource,
  onCrop,
  onReview,
}: {
  row: Compound;
  number: number;
  metrics: string[];
  selected: boolean;
  focused: boolean;
  onSelect: () => void;
  onJump: (row: Compound) => void;
  onActivitySource: (activity: Activity) => void;
  onCrop: (row: Compound) => void;
  onReview: (row: Compound) => void;
}) {
  return (
    <tr data-compound={row.id} className={focused ? 'source-focused' : ''}>
      <td>
        <input
          type="checkbox"
          aria-label={`选择化合物 ${row.display_id}`}
          checked={selected}
          onChange={onSelect}
        />
      </td>
      <td className="row-number">{number}</td>
      <StructureCell row={row} onCrop={onCrop} />
      <ActivitySummary row={row} metrics={metrics} onSource={onActivitySource} />
      <PredictionCells row={row} />
      <td className="source-column">
        <button
          type="button"
          className="link-button"
          aria-label={`${row.display_id} 结构来源${row.source.page === null ? '未知' : `第 ${row.source.page} 页`}`}
          title={String(row.source.paragraph ?? '结构来源定位')}
          disabled={row.source.page === null}
          onClick={() => onJump(row)}
        >
          {row.source.page === null ? '—' : `p.${row.source.page}`}
        </button>
      </td>
      <td className="edit-column">
        <button
          type="button"
          className="toolbar-button"
          data-focus-key={`edit:${row.id}`}
          aria-label={`修正 ${row.display_id}`}
          title="在线修正"
          onClick={() => onReview(row)}
        >
          <Pencil size={14} />
        </button>
      </td>
    </tr>
  );
}
