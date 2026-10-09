import { useTranslation } from '../../i18n';
import type { Compound } from '../../api/types';
import { AssetImage } from '../../components/AssetImage';
import { Dialog } from '../../components/Dialog';
import { confidenceLabels, reviewLabels } from '../../model/presentation';
import { redrawPlaceholder } from '../../model/results';
import { RecognitionDetails } from './RecognitionDetails';
import { cropPlaceholder } from '../../model/extraction';
import { PredictionEvidence } from './PredictionCells';
import { compoundLabel } from '../../model/compoundLabel';
import { ArrowUpRight } from 'lucide-react';

function sourceHref(projectId: string, compoundId: string, page: number | null) {
  return page !== null && Number.isInteger(page) && page > 0
    ? `#/projects/${encodeURIComponent(projectId)}?page=${page}&tab=original&compound=${encodeURIComponent(compoundId)}`
    : null;
}

export function CropDialog({
  compound,
  projectId,
  onClose,
}: {
  compound: Compound;
  projectId: string;
  available?: boolean | null;
  onClose: () => void;
}) {
  const { t } = useTranslation();
  const original = sourceHref(projectId, compound.id, compound.source.page);
  return (
    <Dialog
      title={t('结构详情 · {label}', { label: compoundLabel(compound) })}
      onClose={onClose}
      wide
    >
      <div className="dialog-body crop-detail">
        <div className="crop-comparison" aria-label={t('原始裁图与 SMILES 重绘对照')}>
          <figure>
            <figcaption>
              <span>{t('原始 PDF 裁图')}</span>
              {original && (
                <a className="crop-source-link" href={original} onClick={onClose}>
                  {t('查看原文')}
                  <ArrowUpRight size={14} aria-hidden="true" />
                </a>
              )}
            </figcaption>
            <AssetImage
              url={compound.structure_image_url}
              alt={t('{label} 的原始结构裁图', { label: compoundLabel(compound) })}
              className="crop-large"
              unavailableLabel={cropPlaceholder(compound)}
            />
          </figure>
          <figure>
            <figcaption title={t('原始裁图保留证据；重绘来自当前结构，不证明与原图一致。')}>
              {compound.structure_molfile ? t('结构重绘（非原图）') : t('SMILES 重绘（非原图）')}
            </figcaption>
            <AssetImage
              url={
                compound.smiles?.trim() &&
                (compound.recognition?.status !== 'invalid' ||
                  (compound.correction?.has_changes && !compound.correction.stale))
                  ? compound.redraw_image_url
                  : null
              }
              alt={t('{label} 的 SMILES 重绘（非原图）', { label: compoundLabel(compound) })}
              className="crop-large"
              unavailableLabel={redrawPlaceholder(compound)}
              invalidLabel={t('重绘地址无效')}
              errorLabel={t('重绘加载失败')}
            />
          </figure>
        </div>
        {compound.additional_sources?.length ? (
          <details>
            <summary>
              {t('同一编号的其他原文出处（{count}）', {
                count: compound.additional_sources.length,
              })}
            </summary>
            <p className="muted">
              {t('这些是经过编号与空间证据确认的重复出处，不作为另一个未关联化合物。')}
            </p>
            {compound.additional_sources.map(
              (source, index) =>
                sourceHref(projectId, compound.id, source.page) && (
                  <a
                    key={index}
                    href={sourceHref(projectId, compound.id, source.page)!}
                    onClick={onClose}
                  >
                    {t('原文第 {page} 页', { page: source.page })}
                  </a>
                ),
            )}
          </details>
        ) : null}
        {compound.smiles && (
          <details className="crop-smiles">
            <summary>{t('当前 SMILES')}</summary>
            <textarea aria-label={t('当前 SMILES')} value={compound.smiles} readOnly rows={3} />
          </details>
        )}
        <PredictionEvidence row={compound} />
        <details>
          <summary>{t('原始提取证据 / 校验')}</summary>
          <p className="muted">{t('原始裁图保留证据；重绘来自当前结构，不证明与原图一致。')}</p>
          <dl>
            <dt>{t('来源页')}</dt>
            <dd>{compound.source.page ?? t('未知')}</dd>
            <dt>{t('来源标签')}</dt>
            <dd>{compound.source.source_label ?? t('未提供')}</dd>
            <dt>{t('绑定证据')}</dt>
            <dd>
              {t(confidenceLabels[compound.confidence.level])} ·{' '}
              {compound.confidence.reason ?? t('依据未提供')}
            </dd>
            <dt>{t('人工复核')}</dt>
            <dd>{compound.review ? t(reviewLabels[compound.review.decision]) : t('未复核')}</dd>
          </dl>
          <RecognitionDetails recognition={compound.recognition} />
          {compound.flags.length > 0 && (
            <p className="muted">{t('标记：{flags}', { flags: compound.flags.join('；') })}</p>
          )}
        </details>
      </div>
    </Dialog>
  );
}
