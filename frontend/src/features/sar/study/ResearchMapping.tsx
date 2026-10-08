import { sarPredictionKeys, sarPropertyKeys } from '../../../api/sarStudyTypes';
import { useTranslation } from '../../../i18n';
import type { MappingDraft } from '../csvMapping';
export function ResearchMapping({
  headers,
  draft,
  onChange,
}: {
  headers: string[];
  draft: MappingDraft;
  onChange: (next: MappingDraft) => void;
}) {
  const { t } = useTranslation();
  return (
    <details className="sar-compact">
      <summary>{t('已捕获的性质与预测（可选）')}</summary>
      <p className="sar-hint">{t('仅映射已有数值，不运行模型；未知列不自动分配。')}</p>
      {(['property_columns', 'prediction_columns'] as const).map((kind) => (
        <fieldset key={kind}>
          <legend>{t(kind === 'property_columns' ? '性质' : '已捕获的预测')}</legend>
          <div className="sar-form-grid">
            {(kind === 'property_columns' ? sarPropertyKeys : sarPredictionKeys).map((key) => (
              <label key={key}>
                {key}
                <select
                  value={draft[kind]?.[key] ?? ''}
                  onChange={(event) => {
                    const fields = { ...draft[kind] };
                    if (event.target.value) fields[key] = event.target.value;
                    else delete fields[key];
                    onChange({ ...draft, [kind]: fields });
                  }}
                >
                  <option value="">{t('不映射')}</option>
                  {headers.map((header) => (
                    <option key={header}>{header}</option>
                  ))}
                </select>
              </label>
            ))}
          </div>
        </fieldset>
      ))}
    </details>
  );
}
