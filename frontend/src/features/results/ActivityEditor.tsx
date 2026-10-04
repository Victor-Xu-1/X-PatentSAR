import { activityColumnContext, activityColumnLabel } from '../../model/activityColumns';
import type { ActivityDraft } from './correctionDraft';

export function ActivityEditor({
  values,
  disabled,
  onChange,
}: {
  values: ActivityDraft[];
  disabled: boolean;
  onChange: (values: ActivityDraft[]) => void;
}) {
  return (
    <div className="correction-values" aria-label="活性列数值">
      {values.map((item, index) => {
        const column = { id: String(index), ...item.source };
        const context = activityColumnContext(column);
        const label = activityColumnLabel(column);
        const repeatedName =
          values.filter(
            (row) => row.source.name === item.source.name && row.source.unit === item.source.unit,
          ).length > 1;
        return (
          <label className="form-field" key={index}>
            <span title={[label, context].filter(Boolean).join(' · ')}>{label}</span>
            {repeatedName && context && <small>{context}</small>}
            <input
              aria-label={`修正 ${label} ${index + 1}`}
              value={item.value}
              maxLength={1000}
              disabled={disabled}
              placeholder="—"
              onChange={(event) =>
                onChange(
                  values.map((row, position) =>
                    position === index ? { ...row, value: event.target.value } : row,
                  ),
                )
              }
            />
          </label>
        );
      })}
    </div>
  );
}
