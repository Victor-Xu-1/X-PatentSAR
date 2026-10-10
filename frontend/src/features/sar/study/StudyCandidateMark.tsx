import type { StudyRow } from '../../../api/sarStudyTypes';
import { useTranslation } from '../../../i18n';
import { candidateLabels } from './RowFacts';

/** Presents captured selection/group identity; never computes a rank or score. */
export function StudyCandidateMark({
  row,
  active,
  onOpen,
}: {
  row: StudyRow;
  active: boolean;
  onOpen: () => void;
}) {
  const { t } = useTranslation();
  const selected = row.candidate_status === 'selected';
  const description = [
    t(candidateLabels[row.candidate_status]),
    ...(row.priority_group === null ? [] : [t('优先组') + ' ' + row.priority_group]),
  ].join(' · ');
  if (row.candidate_status === 'not_selected')
    return (
      <span className="sar-candidate-none" title={description}>
        <span className="sr-only">{description}</span>
        <span aria-hidden="true">—</span>
      </span>
    );
  return (
    <button
      type="button"
      className="sar-lead-mark"
      data-selected={selected || undefined}
      disabled={!active}
      title={description}
      aria-label={t('来源详情 · {identifier}', { identifier: row.label }) + ' · ' + description}
      onClick={onOpen}
    >
      <span>{selected ? 'Lead' : t(candidateLabels[row.candidate_status])}</span>
      {selected && row.priority_group !== null && <small>G{row.priority_group}</small>}
    </button>
  );
}
