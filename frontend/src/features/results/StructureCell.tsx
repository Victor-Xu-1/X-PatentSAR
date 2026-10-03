import type { Compound } from '../../api/types';
import { AssetImage } from '../../components/AssetImage';
import { cropPlaceholder } from '../../model/extraction';

export function StructureCell({ row, onCrop }: { row: Compound; onCrop: (row: Compound) => void }) {
  return (
    <td>
      <div className="structure-cell">
        <button
          type="button"
          className="crop-button"
          data-focus-key={`crop:${row.id}`}
          aria-label={`放大 ${row.display_id} 结构裁图`}
          disabled={!row.structure_image_url}
          onClick={() => onCrop(row)}
        >
          <AssetImage
            url={row.structure_image_url}
            alt={`${row.display_id} 结构裁图`}
            unavailableLabel={cropPlaceholder(row)}
          />
        </button>
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
      </div>
    </td>
  );
}
