import { MapPin, Pencil } from 'lucide-react';
import type { Compound } from '../../api/types';
import { ActivityValueCell } from './ActivityValueCell';
import { activityColumnObservations } from '../../model/activityColumns';
import type { ActivitySourceCallback, TableActivityColumn } from '../../model/activityColumns';
import { PredictionCells } from './PredictionCells';
import { StructureCell } from './StructureCell';
import { CompoundCell } from './CompoundCell';
import { LeadCell } from './LeadCell';

export function ResultRow({
  row,
  columns,
  visibleColumns,
  selected,
  focused,
  onSelect,
  onJump,
  onActivitySource,
  onCrop,
  onReview,
}: {
  row: Compound;
  columns: TableActivityColumn[];
  visibleColumns?: ReadonlySet<string>;
  selected: boolean;
  focused: boolean;
  onSelect: () => void;
  onJump: (row: Compound) => void;
  onActivitySource: ActivitySourceCallback;
  onCrop: (row: Compound) => void;
  onReview: (row: Compound) => void;
}) {
  const observations = activityColumnObservations(row, columns);
  const visible = (id: string) => !visibleColumns || visibleColumns.has(id);
  return (
    <tr data-compound={row.id} className={focused ? 'source-focused' : ''}>
      {visible('select') && (
        <td className="frozen-column frozen-select">
          <input
            type="checkbox"
            aria-label={`选择化合物 ${row.display_id}`}
            checked={selected}
            onChange={onSelect}
          />
        </td>
      )}
      {visible('compound') && <CompoundCell row={row} onDetails={onCrop} />}
      {visible('structure') && <StructureCell row={row} onCrop={onCrop} />}
      {visible('lead') && <LeadCell assessment={row.lead} />}
      {columns.map(
        (column, index) =>
          visible(`activity:${column.id}`) && (
            <ActivityValueCell
              key={column.id}
              row={row}
              column={column}
              observations={observations[index]!}
              onSource={onActivitySource}
            />
          ),
      )}
      <PredictionCells row={row} visibleColumns={visibleColumns} />
      {visible('source') && (
        <td className="source-column">
          <button
            type="button"
            className="link-button"
            aria-label={`${row.display_id} 结构来源${row.source.page === null ? '未知' : `第 ${row.source.page} 页`}`}
            title={String(row.source.paragraph ?? '结构来源定位')}
            disabled={row.source.page === null}
            onClick={() => onJump(row)}
          >
            <MapPin size={14} aria-hidden="true" />
          </button>
        </td>
      )}
      {visible('edit') && (
        <td className="edit-column frozen-column frozen-edit">
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
      )}
    </tr>
  );
}
