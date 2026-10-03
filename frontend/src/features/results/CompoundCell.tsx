import type { Compound } from '../../api/types';

export function CompoundCell({
  row,
  onDetails,
}: {
  row: Compound;
  onDetails: (row: Compound) => void;
}) {
  const corrected = Boolean(row.correction?.has_changes && !row.correction.stale && row.smiles);
  const displayLabel =
    row.record_kind === 'structure_only' &&
    row.display_id.startsWith('未关联结构 ') &&
    (!row.correction?.has_changes || row.correction.stale)
      ? row.display_id.replace(/ · p\.\d+$/, '')
      : row.display_id;
  return (
    <td className="compound-column frozen-column frozen-compound">
      <div className="compound-identity">
        <button
          type="button"
          className="compound-detail-button"
          data-focus-key={`detail:${row.id}`}
          aria-label={`查看 ${row.display_id} 结构详情`}
          title={row.display_id}
          onClick={() => onDetails(row)}
        >
          {displayLabel}
        </button>
        {row.correction?.stale ? (
          <small className="correction">待重核</small>
        ) : row.correction?.has_changes ? (
          <small className="correction">{corrected ? '已修正 · 重绘' : '已修正'}</small>
        ) : null}
        {row.record_kind === 'activity_only' && <small className="muted">结构待定位</small>}
        {row.record_kind === 'structure_only' && !row.activities.length && (
          <small className="muted">未关联活性</small>
        )}
      </div>
    </td>
  );
}
