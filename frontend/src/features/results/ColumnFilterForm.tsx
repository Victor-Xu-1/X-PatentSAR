import { useTranslation, UiError, errorText } from '../../i18n';
import { useState } from 'react';
import type { ActivityBand, ActivityColumn, ColumnFilter, Filters } from '../../api/types';
import { activityBands } from '../../api/types';
import type { ResultColumn } from '../../model/resultColumns';
import {
  columnFilterDraft,
  columnFilterModes,
  compileColumnFilter,
  defaultColumnKind,
} from '../../model/columnFilters';
import { compileValueSelection, restoreValueSelection } from '../../model/columnValueSelection';
import { ColumnConditionFields } from './ColumnConditionFields';
import { ColumnValueChecklist } from './ColumnValueChecklist';
import { ColumnBandChoices } from './ColumnBandChoices';
import { useFilterValues } from './useFilterValues';

type DraftMode = 'values' | 'condition' | 'band';
export function ColumnFilterForm({
  projectId,
  column,
  activity,
  filters,
  disabled,
  onApply,
  onCancel,
  onSortBand,
}: {
  projectId: string | undefined;
  column: ResultColumn;
  activity: ActivityColumn | undefined;
  filters: Filters;
  disabled: boolean;
  onApply: (filters: ColumnFilter[]) => void;
  onCancel: () => void;
  onSortBand: (band: ActivityBand) => void;
}) {
  const { t } = useTranslation();
  const own = (filters.column_filters ?? []).filter((item) => item.column === column.id);
  const fallbackKind = defaultColumnKind(column, activity);
  const [mode, setMode] = useState<DraftMode>(() => {
    if (own[0]?.op === 'band') return 'band';
    return (own.length && !['in', 'not_in'].includes(own[0]!.op)) || fallbackKind === 'presence'
      ? 'condition'
      : 'values';
  });
  const [selection, setSelection] = useState(() => restoreValueSelection(column.id, own));
  const [condition, setCondition] = useState(() =>
    columnFilterDraft(column.id, own, columnFilterModes(fallbackKind)[0]!),
  );
  const [conditionTouched, setConditionTouched] = useState(() =>
    own.some((item) => !['in', 'not_in', 'band'].includes(item.op)),
  );
  const [band, setBand] = useState<ActivityBand | ''>(
    () => activityBands.find((value) => own[0]?.op === 'band' && value === own[0].value) ?? '',
  );
  const [sortColors, setSortColors] = useState(false);
  const [error, setError] = useState<Error | null>(null);
  const [search, setSearch] = useState('');
  const [page, setPage] = useState(1);
  const choices = useFilterValues(projectId, column.id, filters, search, page);
  const kind = choices.kind ?? fallbackKind;
  const modes = columnFilterModes(kind);
  const activeCondition = {
    ...condition,
    op: conditionTouched || modes.includes(condition.op) ? condition.op : modes[0]!,
  };
  const scale = activity?.strength_scale;
  const knownScale = Boolean(
    scale &&
    scale.direction !== 'unknown' &&
    scale.eligible &&
    scale.strong_boundary !== null &&
    scale.medium_boundary !== null,
  );
  const colorsAvailable = knownScale && Boolean(choices.data?.bands?.length);
  function chooseMode(next: DraftMode) {
    setMode(next);
    setSortColors(false);
    setError(null);
  }
  return (
    <form
      className="column-filter-form"
      onSubmit={(event) => {
        event.preventDefault();
        try {
          if (mode === 'condition') onApply(compileColumnFilter(column.id, activeCondition, kind));
          else if (mode === 'band') {
            if (!colorsAvailable || !band) throw new UiError('请选择可用的颜色分档。');
            onApply([{ column: column.id, op: 'band', value: band }]);
          } else {
            if (!choices.data || choices.loading || choices.error)
              throw new UiError('请先加载取值，再确定筛选。');
            onApply(compileValueSelection(column.id, selection));
          }
        } catch (failure) {
          setError(failure instanceof Error ? failure : new UiError('筛选条件无效。'));
        }
      }}
    >
      {activity && (
        <>
          <button
            type="button"
            className="column-detail-toggle"
            aria-expanded={sortColors}
            aria-pressed={sortColors}
            disabled={disabled || !colorsAvailable}
            onClick={() => setSortColors(!sortColors)}
          >
            {t('按颜色排序')}
          </button>
          {sortColors && (
            <ColumnBandChoices
              bands={choices.data?.bands}
              selected={filters.sort_column === column.id ? filters.sort_band : ''}
              disabled={disabled || !colorsAvailable}
              action="排序"
              onChoose={onSortBand}
            />
          )}
          <button
            type="button"
            className="column-detail-toggle"
            aria-expanded={mode === 'band' && !sortColors}
            aria-pressed={mode === 'band' && !sortColors}
            disabled={disabled || !colorsAvailable}
            onClick={() => chooseMode(mode === 'band' ? 'values' : 'band')}
          >
            {t('按颜色筛选')}
          </button>
          {mode === 'band' && !sortColors && (
            <ColumnBandChoices
              bands={choices.data?.bands}
              selected={band}
              disabled={disabled || !colorsAvailable}
              action="筛选"
              onChoose={(next) => {
                setBand(next);
                chooseMode('band');
              }}
            />
          )}
          {!knownScale && <small className="muted">{t('分档未知，未推断颜色。')}</small>}
        </>
      )}
      {kind !== 'presence' && (
        <button
          type="button"
          className="column-detail-toggle"
          aria-expanded={mode === 'condition' && !sortColors}
          aria-pressed={mode === 'condition' && !sortColors}
          disabled={disabled}
          onClick={() => chooseMode(mode === 'condition' ? 'values' : 'condition')}
        >
          {kind === 'number' ? t('数字筛选') : t('文本筛选')}
        </button>
      )}
      {mode === 'condition' && !sortColors && (
        <ColumnConditionFields
          kind={kind}
          draft={activeCondition}
          disabled={disabled}
          onChange={(next) => {
            setCondition(next);
            setConditionTouched(true);
            chooseMode('condition');
          }}
        />
      )}
      {kind !== 'presence' && (
        <>
          {(mode !== 'values' || sortColors) && (
            <button
              type="button"
              className="column-detail-toggle"
              disabled={disabled}
              onClick={() => chooseMode('values')}
            >
              {t('选择取值')}
            </button>
          )}
          {mode === 'values' && !sortColors && (
            <ColumnValueChecklist
              choices={choices.data}
              selection={selection}
              search={search}
              page={page}
              disabled={disabled || choices.loading}
              onSearch={(next) => {
                setSearch(next);
                setPage(1);
              }}
              onPage={setPage}
              onChange={(next) => {
                setSelection(next);
                chooseMode('values');
              }}
              onError={setError}
            />
          )}
        </>
      )}
      {choices.loading && <output className="muted">{t('正在加载取值…')}</output>}
      {choices.error && (
        <div className="column-choice-error">
          <small role="alert">
            {t('无法加载取值。{error} 条件筛选仍可使用。', {
              error:
                choices.error instanceof UiError ? errorText(choices.error) : choices.error.message,
            })}
          </small>
          <button type="button" onClick={choices.reload}>
            {t('重试取值')}
          </button>
        </div>
      )}
      {error && (
        <small role="alert" className="error-notice">
          {error instanceof UiError ? errorText(error) : error.message}
        </small>
      )}
      <div className="column-menu-actions">
        <button
          type="submit"
          className="primary"
          disabled={
            disabled ||
            sortColors ||
            Boolean(error) ||
            (mode === 'values' && !choices.data) ||
            (mode === 'band' && (!colorsAvailable || !band))
          }
        >
          {t('确定')}
        </button>
        <button type="button" onClick={onCancel}>
          {t('取消')}
        </button>
      </div>
    </form>
  );
}
