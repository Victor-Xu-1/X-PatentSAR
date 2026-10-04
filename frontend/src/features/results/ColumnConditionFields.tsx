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
  const scalar = !['empty', 'not_empty'].includes(draft.op);
  const modes = columnFilterModes(kind);
  return (
    <div className="column-condition-fields">
      <label>
        条件
        <select
          aria-label="筛选方式"
          value={draft.op}
          disabled={disabled}
          onChange={(event) => onChange({ ...draft, op: event.target.value as FilterMode })}
        >
          {!modes.includes(draft.op) && (
            <option value={draft.op} disabled>
              {filterLabels[draft.op]}（已有条件，请重新选择）
            </option>
          )}
          {modes.map((mode) => (
            <option key={mode} value={mode}>
              {filterLabels[mode]}
            </option>
          ))}
        </select>
      </label>
      {scalar && (
        <input
          aria-label={draft.op === 'range' ? '筛选下限' : '筛选值'}
          placeholder={draft.op === 'range' ? '下限' : '值…'}
          maxLength={1000}
          disabled={disabled}
          value={draft.value}
          onChange={(event) => onChange({ ...draft, value: event.target.value })}
        />
      )}
      {draft.op === 'range' && (
        <input
          aria-label="筛选上限"
          placeholder="上限"
          maxLength={1000}
          disabled={disabled}
          value={draft.upper}
          onChange={(event) => onChange({ ...draft, upper: event.target.value })}
        />
      )}
    </div>
  );
}
