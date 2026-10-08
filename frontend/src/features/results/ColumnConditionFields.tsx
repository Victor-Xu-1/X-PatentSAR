import { useTranslation } from '../../i18n';
import type { FilterValueKind } from '../../api/types';
import { columnFilterModes, filterLabels } from '../../model/columnFilters';
import type { FilterDraft, FilterMode } from '../../model/columnFilters';

export function ColumnConditionFields({
  kind,
  draft,
  disabled,
  onChange,
}: {
  kind: FilterValueKind;
  draft: FilterDraft;
  disabled: boolean;
  onChange: (draft: FilterDraft) => void;
}) {
  const { t } = useTranslation();
  const scalar = !['empty', 'not_empty'].includes(draft.op);
  const modes = columnFilterModes(kind);
  return (
    <div className="column-condition-fields">
      <label>
        {t('条件')}
        <select
          aria-label={t('筛选方式')}
          value={draft.op}
          disabled={disabled}
          onChange={(event) => onChange({ ...draft, op: event.target.value as FilterMode })}
        >
          {!modes.includes(draft.op) && (
            <option value={draft.op} disabled>
              {t('{condition}（已有条件，请重新选择）', { condition: t(filterLabels[draft.op]) })}
            </option>
          )}
          {modes.map((mode) => (
            <option key={mode} value={mode}>
              {t(filterLabels[mode])}
            </option>
          ))}
        </select>
      </label>
      {scalar && (
        <input
          aria-label={draft.op === 'range' ? t('筛选下限') : t('筛选值')}
          placeholder={draft.op === 'range' ? t('下限') : t('值…')}
          maxLength={1000}
          disabled={disabled}
          value={draft.value}
          onChange={(event) => onChange({ ...draft, value: event.target.value })}
        />
      )}
      {draft.op === 'range' && (
        <input
          aria-label={t('筛选上限')}
          placeholder={t('上限')}
          maxLength={1000}
          disabled={disabled}
          value={draft.upper}
          onChange={(event) => onChange({ ...draft, upper: event.target.value })}
        />
      )}
    </div>
  );
}
