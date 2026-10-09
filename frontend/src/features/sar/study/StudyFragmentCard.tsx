import type { StudyFragment, StudyReport } from '../../../api/sarStudyTypes';
import { useTranslation } from '../../../i18n';
import { StudyImage } from './StudyImage';
import { StudyBars } from './StudyBars';
import { FragmentComparisons } from './FragmentComparisons';
import { hasStrongRule } from './StudyPolicyNote';
import type { CountingUnit } from './chartPresentation';

export function StudyFragmentCard({
  fragment,
  index,
  regionId,
  referenceId,
  jobId,
  active,
  onRows,
  unit,
  report,
  onPreview,
}: {
  fragment: StudyFragment;
  index: number;
  regionId: string;
  referenceId: string;
  jobId: string;
  active: boolean;
  unit: CountingUnit;
  report: StudyReport;
  onRows: (region: string, fragment: string) => void;
  onPreview: (id: string) => void;
}) {
  const { t } = useTranslation();
  const candidate = fragment.molecule_ids.find((id) => id !== referenceId);
  return (
    <article className="sar-study-card">
      <h4>
        {t('片段 {index}', { index })}
        {fragment.is_reference && <small> · {t('参考')}</small>}
      </h4>
      <StudyImage
        jobId={jobId}
        kind="fragment"
        identifier={fragment.id}
        regionId={regionId}
        label={fragment.smiles}
        active={active}
      />
      <StudyBars
        bins={fragment.bins}
        layout="stack"
        controlledUnit={unit}
        showLegend={false}
        countingContract={report.counting_contract}
        direction={report.policies[0]?.direction}
      />
      {hasStrongRule(report.policies[0]) && (
        <p>
          {t('强活性 {strong}/{total}', {
            strong: fragment.strong_count,
            total: fragment.molecule_count,
          })}
        </p>
      )}
      <FragmentComparisons fragment={fragment} />
      <button
        type="button"
        onClick={() => onRows(regionId, fragment.id)}
        title={t('查看支持与反例')}
      >
        {t('查看分子')}
      </button>
      {candidate && (
        <button
          type="button"
          className="primary sar-preview-trigger"
          onClick={() => onPreview(candidate)}
        >
          {t('查看改造与变化')}
        </button>
      )}
    </article>
  );
}
