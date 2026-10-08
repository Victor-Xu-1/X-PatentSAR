import { useTranslation } from '../../i18n';
import { METRIC_SPECS } from '../../api/predictionTypes';
import type { CorrectionDraft } from './correctionDraft';

export function PropertyEditor({
  values,
  disabled,
  onChange,
}: {
  values: CorrectionDraft['properties'];
  disabled: boolean;
  onChange: (values: CorrectionDraft['properties']) => void;
}) {
  const { t } = useTranslation();
  return (
    <div className="correction-values correction-properties" aria-label={t('指标列数值')}>
      {METRIC_SPECS.map(({ key, label, unit }) => (
        <label className="form-field" key={key}>
          <span title={`${label} · ${unit}`}>{label}</span>
          <input
            aria-label={t('修正 {label}', { label })}
            type="text"
            inputMode="decimal"
            maxLength={64}
            value={values[key].value}
            disabled={disabled}
            placeholder="—"
            onChange={(event) =>
              onChange({
                ...values,
                [key]: { ...values[key], value: event.target.value, touched: true },
              })
            }
          />
        </label>
      ))}
    </div>
  );
}
