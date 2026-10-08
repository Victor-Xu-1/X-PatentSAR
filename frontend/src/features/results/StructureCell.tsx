import type { Compound } from '../../api/types';
import { AssetImage } from '../../components/AssetImage';
import { cropPlaceholder } from '../../model/extraction';
import { redrawPlaceholder } from '../../model/results';
import { compoundLabel } from '../../model/compoundLabel';

export function StructureCell({ row, onCrop }: { row: Compound; onCrop: (row: Compound) => void }) {
  const corrected = Boolean(row.correction?.has_changes && !row.correction.stale && row.smiles);
  const image = corrected ? row.redraw_image_url : row.structure_image_url;
  const label = corrected ? '修正重绘' : '结构裁图';
  const identifier = compoundLabel(row);
  return (
    <td className="frozen-column frozen-structure">
      <div className="structure-cell">
        <button
          type="button"
          className="crop-button"
          data-focus-key={`crop:${row.id}`}
          aria-label={`放大 ${identifier} ${label}`}
          disabled={!image}
          onClick={() => onCrop(row)}
        >
          <AssetImage
            url={image}
            alt={`${identifier} ${label}`}
            unavailableLabel={corrected ? redrawPlaceholder(row) : cropPlaceholder(row)}
          />
        </button>
      </div>
    </td>
  );
}
