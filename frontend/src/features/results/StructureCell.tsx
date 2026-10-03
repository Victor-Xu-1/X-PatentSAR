import type { Compound } from '../../api/types';
import { AssetImage } from '../../components/AssetImage';
import { cropPlaceholder } from '../../model/extraction';
import { redrawPlaceholder } from '../../model/results';

export function StructureCell({ row, onCrop }: { row: Compound; onCrop: (row: Compound) => void }) {
  const corrected = Boolean(row.correction?.has_changes && !row.correction.stale && row.smiles);
  const image = corrected ? row.redraw_image_url : row.structure_image_url;
  const label = corrected ? '修正重绘' : '结构裁图';
  return (
    <td>
      <div className="structure-cell">
        <button
          type="button"
          className="crop-button"
          data-focus-key={`crop:${row.id}`}
          aria-label={`放大 ${row.display_id} ${label}`}
          disabled={!image}
          onClick={() => onCrop(row)}
        >
          <AssetImage
            url={image}
            alt={`${row.display_id} ${label}`}
            unavailableLabel={corrected ? redrawPlaceholder(row) : cropPlaceholder(row)}
          />
        </button>
        <div className="structure-identity">
          <button
            type="button"
            className="structure-detail-button"
            data-focus-key={`detail:${row.id}`}
            aria-label={`查看 ${row.display_id} 结构详情`}
            title={row.id}
            onClick={() => onCrop(row)}
          >
            {row.display_id}
          </button>
          {row.correction?.stale ? (
            <small className="correction">待重核</small>
          ) : row.correction?.has_changes ? (
            <small className="correction">{corrected ? '已修正 · 重绘' : '已修正'}</small>
          ) : null}
          {row.record_kind === 'activity_only' && <small className="muted">结构待定位</small>}
        </div>
      </div>
    </td>
  );
}
