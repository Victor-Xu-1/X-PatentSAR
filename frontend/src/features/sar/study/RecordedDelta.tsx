import type { RecordedDifference } from '../../../api/sarStudyTypes';
import { useTranslation } from '../../../i18n';
import { differenceText } from './tablePresentation';

const labels = {
  comparable: '数值差，不代表优劣',
  missing: '未测定',
  context_mismatch: '条件不可比',
  indeterminate: '不可判定',
  not_scalar: '仅精确数值可计算差值',
  not_representable: '数值差超出显示范围',
} as const;

/** Descriptive arithmetic remains neutral: never activity color or a better/worse arrow. */
export function RecordedDelta({ difference }: { difference: RecordedDifference | undefined }) {
  const { t } = useTranslation();
  const label = t(difference ? labels[difference.status] : '未纳入本次统计');
  return (
    <span className="sar-recorded-delta" title={label} aria-label={label}>
      {difference?.status === 'comparable' && difference.value !== null
        ? `Δ ${difference.value > 0 ? '+' : ''}${differenceText(difference.value)}`
        : '—'}
    </span>
  );
}
