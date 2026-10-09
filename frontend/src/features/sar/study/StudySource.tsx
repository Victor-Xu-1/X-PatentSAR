import { useCallback } from 'react';
import { sarApi } from '../../../api/sarApi';
import type { Dataset } from '../../../api/sarTypes';
import type { StudyContext, StudyRow } from '../../../api/sarStudyTypes';
import { Loading } from '../../../components/Feedback';
import { useTranslation } from '../../../i18n';
import { MoleculeEvidence } from '../MoleculeEvidence';
import { SARFailure } from '../SARFailure';
import { useSARResource } from '../useSARResource';
import { RowFacts } from './RowFacts';
export function StudySource({
  dataset,
  id,
  row,
  contexts,
  active,
  onClose,
}: {
  dataset: Dataset;
  id: string;
  row: StudyRow | null;
  contexts: StudyContext[];
  active: boolean;
  onClose: () => void;
}) {
  const { t } = useTranslation();
  const load = useCallback(
    (signal: AbortSignal) => sarApi.molecule(dataset.id, id, signal),
    [dataset.id, id],
  );
  const source = useSARResource('sar:study-source:' + dataset.id + ':' + id, active, load);
  return (
    <aside className="sar-source-detail" aria-label={t('来源详情')}>
      <div className="sar-section-heading">
        <h3>{t('来源详情')}</h3>
        <button type="button" onClick={onClose}>
          {t('关闭对话框')}
        </button>
      </div>
      {source.loading && <Loading />}
      {source.error && <SARFailure error={source.error} onRetry={source.reload} />}
      {source.data && (
        <details className="sar-compact">
          <summary>{t('原始记录')}</summary>
          <MoleculeEvidence dataset={dataset} molecule={source.data} />
        </details>
      )}
      {row && <RowFacts row={row} contexts={contexts} />}
    </aside>
  );
}
