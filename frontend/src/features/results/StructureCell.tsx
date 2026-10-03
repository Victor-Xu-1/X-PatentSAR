import type { Compound } from '../../api/types';
import { AssetImage } from '../../components/AssetImage';
import { cropPlaceholder } from '../../model/extraction';
import { redrawPlaceholder } from '../../model/results';

export function StructureCell({ row, onCrop }: { row: Compound; onCrop: (row: Compound) => void }) {
  const corrected = Boolean(row.correction?.has_changes && !row.correction.stale && row.smiles);
  const image = corrected ? row.redraw_image_url : row.structure_image_url;
  const label = corrected ? '修正重绘' : '结构裁图';
  return (
    <td className="frozen-column frozen-structure">
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
      </div>
    </td>
  );
}
