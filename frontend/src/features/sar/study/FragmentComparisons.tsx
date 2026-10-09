import type { StudyFragment } from '../../../api/sarStudyTypes';
import { useTranslation } from '../../../i18n';

const outcomes = [
  ['better', '更强'],
  ['worse', '更弱'],
  ['indeterminate', '未确定'],
  ['missing', '缺失'],
] as const;

/** Captured reference comparisons, not normalized molecular shares or a score. */
export function FragmentComparisons({
  fragment,
}: {
  fragment: Pick<StudyFragment, 'better' | 'worse' | 'indeterminate' | 'missing'>;
}) {
  const { t } = useTranslation();
  return (
    <fieldset className="sar-fragment-comparisons">
      <legend className="sr-only">{t('参考比较结果')}</legend>
      <dl>
        {outcomes.map(([key, label]) => (
          <div key={key} data-outcome={key} data-empty={fragment[key] === 0 || undefined}>
            <dt>{t(label)}</dt>
            <dd>{fragment[key]}</dd>
          </div>
        ))}
      </dl>
    </fieldset>
  );
}
