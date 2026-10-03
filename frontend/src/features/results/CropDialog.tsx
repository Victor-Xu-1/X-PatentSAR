import type { Compound } from '../../api/types';
import { AssetImage } from '../../components/AssetImage';
import { Dialog } from '../../components/Dialog';
import { confidenceLabels, reviewLabels } from '../../model/presentation';
import { redrawPlaceholder } from '../../model/results';
import { RecognitionDetails } from './RecognitionDetails';
import { cropPlaceholder } from '../../model/extraction';
import { PredictionEvidence } from './PredictionCells';

export function CropDialog({
  compound,
  onClose,
}: {
  compound: Compound;
  projectId: string;
  available?: boolean | null;
  onClose: () => void;
}) {
  return (
    <Dialog title={`结构详情 · ${compound.display_id}`} onClose={onClose} wide>
      <div className="dialog-body crop-detail">
        <div className="crop-comparison" aria-label="原始裁图与 SMILES 重绘对照">
          <figure>
            <figcaption>原始 PDF 裁图</figcaption>
            <AssetImage
              url={compound.structure_image_url}
              alt={`${compound.display_id} 的原始结构裁图`}
              className="crop-large"
              unavailableLabel={cropPlaceholder(compound)}
            />
          </figure>
          <figure>
            <figcaption>SMILES 重绘（非原图）</figcaption>
            <AssetImage
              url={
                compound.smiles?.trim() &&
                (compound.recognition?.status !== 'invalid' ||
                  (compound.correction?.has_changes && !compound.correction.stale))
                  ? compound.redraw_image_url
                  : null
              }
              alt={`${compound.display_id} 的 SMILES 重绘（非原图）`}
              className="crop-large"
              unavailableLabel={redrawPlaceholder(compound)}
              invalidLabel="重绘地址无效"
              errorLabel="重绘加载失败"
            />
          </figure>
        </div>
        <p className="muted">原始裁图保留证据；重绘来自当前 SMILES，不证明与原图一致。</p>
        {compound.smiles && (
          <label className="form-field">
            当前 SMILES
            <textarea value={compound.smiles} readOnly rows={3} />
          </label>
        )}
        <PredictionEvidence row={compound} />
        <details>
          <summary>原始提取证据 / 校验</summary>
          <dl>
            <dt>来源页</dt>
            <dd>{compound.source.page ?? '未知'}</dd>
            <dt>来源标签</dt>
            <dd>{compound.source.source_label ?? '未提供'}</dd>
            <dt>绑定证据</dt>
            <dd>
              {confidenceLabels[compound.confidence.level]} ·{' '}
              {compound.confidence.reason ?? '依据未提供'}
            </dd>
            <dt>人工复核</dt>
            <dd>{compound.review ? reviewLabels[compound.review.decision] : '未复核'}</dd>
          </dl>
          <RecognitionDetails recognition={compound.recognition} />
          {compound.flags.length > 0 && <p className="muted">标记：{compound.flags.join('；')}</p>}
        </details>
      </div>
    </Dialog>
  );
}
