import type { IndicatorDefault } from '../../api/sarStudyTypes';
import { useTranslation } from '../../i18n';

export function IndicatorDirection({
  value,
  hint,
  onChange,
}: {
  value: '' | 'lower' | 'higher';
  hint?: IndicatorDefault | undefined;
  onChange: (value: '' | 'lower' | 'higher') => void;
}) {
  const { t } = useTranslation();
  if (hint && hint.direction !== 'unknown')
    return (
      <output className="sar-hint" aria-label={t('活性方向')}>
        {t('自动 · {direction}', {
          direction: t(hint.direction === 'lower' ? '值越低活性越强' : '值越高活性越强'),
        })}
      </output>
    );
  return (
    <label>
      {t('活性方向')}
      <select value={value} onChange={(event) => onChange(event.target.value as typeof value)}>
        <option value="">{t('请选择方向')}</option>
        <option value="lower">{t('越低越强')}</option>
        <option value="higher">{t('越高越强')}</option>
      </select>
    </label>
  );
}
