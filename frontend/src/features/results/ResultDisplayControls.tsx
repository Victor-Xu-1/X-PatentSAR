import { useTranslation } from '../../i18n';
import type { ResultDensity } from '../../model/results';

export function ResultDisplayControls({
  density,
  onDensity,
  disabled,
}: {
  density: ResultDensity;
  onDensity: (value: ResultDensity) => void;
  disabled: boolean;
}) {
  const { t } = useTranslation();
  return (
    <div className="result-display-controls">
      <fieldset className="density-controls">
        <legend className="sr-only">{t('结果表格密度')}</legend>
        {(['compact', 'comfortable'] as const).map((value) => (
          <button
            key={value}
            type="button"
            aria-pressed={density === value}
            disabled={disabled}
            onClick={() => onDensity(value)}
          >
            {value === 'compact' ? t('紧凑视图') : t('舒适视图')}
          </button>
        ))}
      </fieldset>
      <p className="activity-strength-legend" aria-label={t('活性颜色说明')}>
        <span data-activity-strength="strong">{t('相对强')}</span>
        <span data-activity-strength="medium">{t('中档')}</span>
        <span>{t('其余 / 未分档')}</span>
        {t('同列全项目排名，并列同色；不跨实验比较，不代表绝对活性。')}
      </p>
    </div>
  );
}
