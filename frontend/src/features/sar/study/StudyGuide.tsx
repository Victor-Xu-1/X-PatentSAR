import { useTranslation } from '../../../i18n';

/** Navigation guidance only; existing import/study owners still control writes. */
export function StudyGuide({ current }: { current: 1 | 2 | 3 }) {
  const { t } = useTranslation();
  return (
    <ol className="sar-study-guide" aria-label={t('分析步骤')}>
      {['选择数据', '选择活性', '开始分析'].map((label, index) => (
        <li
          key={label}
          className={index + 1 === current ? 'is-active' : index + 1 < current ? 'is-done' : ''}
          aria-current={index + 1 === current ? 'step' : undefined}
        >
          <span aria-hidden="true">{index + 1}</span>
          {t(label)}
        </li>
      ))}
    </ol>
  );
}
