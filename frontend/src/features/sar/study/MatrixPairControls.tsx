import { ChevronLeft, ChevronRight } from 'lucide-react';
import type { StudyMatrix } from '../../../api/sarStudyTypes';
import { useTranslation } from '../../../i18n';

/** Navigate the current complete matrix page, without a second read or calculation. */
export function MatrixPairControls({
  data,
  index,
  onSelect,
}: {
  data: StudyMatrix;
  index: number;
  onSelect: (id: string) => void;
}) {
  const { t } = useTranslation();
  const candidates = data.previews.map((item) => item.candidate);
  return (
    <div className="sar-matrix-pair-controls">
      <button
        type="button"
        aria-label={t('向左查看结构')}
        disabled={index === 0}
        onClick={() => onSelect(candidates[index - 1]!.molecule_id)}
      >
        <ChevronLeft size={16} />
      </button>
      <select
        aria-label={t('对比分子')}
        value={candidates[index]!.molecule_id}
        onChange={(event) => onSelect(event.target.value)}
      >
        {candidates.map((candidate, order) => (
          <option key={candidate.molecule_id} value={candidate.molecule_id}>
            {candidate.label} · {order + 1}/{candidates.length}
          </option>
        ))}
      </select>
      <button
        type="button"
        aria-label={t('向右查看结构')}
        disabled={index === candidates.length - 1}
        onClick={() => onSelect(candidates[index + 1]!.molecule_id)}
      >
        <ChevronRight size={16} />
      </button>
    </div>
  );
}
