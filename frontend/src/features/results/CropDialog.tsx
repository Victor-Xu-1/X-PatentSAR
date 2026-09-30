import type { Compound } from '../../api/types';
import { AssetImage } from '../../components/AssetImage';
import { Dialog } from '../../components/Dialog';
import { confidenceLabels } from '../../model/presentation';
import { useState } from 'react';
import { api, safeAssetUrl } from '../../api';
import { useAnalysis } from '../analysis/useAnalysis';
import type { RecognitionResult } from '../../api/analysisTypes';
import { AdmetPanel } from '../analysis/AdmetPanel';
import { AnalysisFeedback } from '../analysis/AnalysisFeedback';
export function CropDialog({
  compound,
  projectId,
  available = null,
  onClose,
}: {
  compound: Compound;
  projectId: string;
  available?: boolean | null;
  onClose: () => void;
}) {
  const recognize = useAnalysis<RecognitionResult>();
  const [admetBusy, setAdmetBusy] = useState(false);
  const recognizedSmiles =
    recognize.result?.status === 'recognized' ? recognize.result.smiles : null;
  return (
    <Dialog
      title={`结构原始裁图 · ${compound.display_id}`}
      onClose={onClose}
      wide
      busy={recognize.busy || admetBusy}
    >
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
        <section className="crop-recognition">
          <button
            type="button"
            disabled={
              recognize.busy ||
              recognize.uncertain ||
              admetBusy ||
              !safeAssetUrl(compound.structure_image_url)
            }
            onClick={() =>
              void recognize.run((signal) => api.recognize(projectId, compound.id, signal))
            }
          >
            识别真实裁图（DECIMER + QC）
          </button>
          <p className="muted">
            仅调用此项目的真实裁图，不用生成图片或修改正式提取结果；也可在下方直接输入 SMILES。
          </p>
          <AnalysisFeedback {...recognize} pendingLabel="正在识别真实裁图并执行 RDKit QC…" />
          {recognize.result && (
            <output
              className={
                recognize.result.status === 'recognized' ? 'success-banner' : 'error-notice'
              }
            >
              {recognize.result.engine.name} · {recognize.result.engine.version} ·{' '}
              {recognize.result.status === 'recognized'
                ? '独立识别通过 QC，仅供分析'
                : '识别被 QC 拒绝，不会当作有效 SMILES'}
              {recognize.result.warnings.map((warning, i) => (
                <p key={i}>{warning}</p>
              ))}
            </output>
          )}
        </section>
        <AdmetPanel
          available={available}
          initialSmiles={recognizedSmiles ?? compound.smiles ?? ''}
          blocked={recognize.busy || recognize.uncertain}
          onBusy={setAdmetBusy}
        />
      </div>
    </Dialog>
  );
}
