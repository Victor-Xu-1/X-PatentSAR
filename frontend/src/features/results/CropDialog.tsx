import type { Compound } from '../../api/types';
import { AssetImage } from '../../components/AssetImage';
import { Dialog } from '../../components/Dialog';
import { confidenceLabels } from '../../model/presentation';
export function CropDialog({ compound, onClose }: { compound: Compound; onClose: () => void }) {
  return (
    <Dialog title={`结构原始裁图 · ${compound.display_id}`} onClose={onClose} wide>
      <div className="dialog-body crop-detail">
        <AssetImage
          url={compound.structure_image_url}
          alt={`${compound.display_id} 的原始结构裁图`}
          className="crop-large"
        />
        <dl>
          <dt>来源页码</dt>
          <dd>{compound.source.page ?? '未知'}</dd>
          <dt>来源标签</dt>
          <dd>{compound.source.source_label ?? '未提供'}</dd>
          <dt>置信度</dt>
          <dd>
            {confidenceLabels[compound.confidence.level]}
            {compound.confidence.score !== null
              ? ` · ${compound.confidence.score}`
              : ' · 无数值分数'}
          </dd>
          <dt>依据</dt>
          <dd>{compound.confidence.reason ?? '未提供'}</dd>
        </dl>
        {compound.smiles && (
          <label className="form-field">
            服务端 SMILES
            <textarea value={compound.smiles} readOnly rows={3} />
          </label>
        )}
        {compound.flags.length > 0 && <p className="muted">标记：{compound.flags.join('；')}</p>}
      </div>
    </Dialog>
  );
}
