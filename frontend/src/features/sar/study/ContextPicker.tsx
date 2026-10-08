import { useState } from 'react';
import type { StudyContext } from '../../../api/sarStudyTypes';
import { useTranslation } from '../../../i18n';
import { PageControls } from '../PageControls';
import { contextLabel } from './policyDraft';
export function ContextPicker({
  contexts,
  selected,
  onSelect,
}: {
  contexts: StudyContext[];
  selected: string[];
  onSelect: (id: string, checked: boolean) => void;
}) {
  const { t } = useTranslation();
  const [query, setQuery] = useState(''),
    [page, setPage] = useState(1);
  const visible = contexts.filter((c) =>
    [c.name, c.unit, ...Object.entries(c.context).flat()].some((v) => v?.includes(query)),
  );
  return (
    <fieldset className="sar-context-picker">
      <legend>
        {t('精确实验条件')} · {selected.length}/8
      </legend>
      <label>
        {t('查找实验条件')}
        <input
          type="search"
          maxLength={200}
          value={query}
          onChange={(e) => {
            setQuery(e.target.value);
            setPage(1);
          }}
        />
      </label>
      <div className="sar-context-list">
        {visible.slice((page - 1) * 50, page * 50).map((context) => (
          <label
            className="sar-context-choice"
            key={context.id}
            aria-label={[
              contextLabel(context),
              ...Object.entries(context.context).map(([key, value]) => key + ': ' + (value ?? '—')),
            ].join(' · ')}
          >
            <input
              type="checkbox"
              checked={selected.includes(context.id)}
              disabled={selected.length >= 8 && !selected.includes(context.id)}
              onChange={(e) => onSelect(context.id, e.target.checked)}
            />
            <span>
              <strong>{contextLabel(context)}</strong>
              <small>
                {Object.entries(context.context)
                  .map(([key, value]) => key + ': ' + (value ?? '—'))
                  .join(' · ')}
              </small>
              <small>
                {t('{molecules} 个分子 · {observations} 条观察', {
                  molecules: context.molecule_count,
                  observations: context.observation_count,
                })}
              </small>
              <small>{context.value_samples.join(' · ')}</small>
            </span>
          </label>
        ))}
      </div>
      {!visible.length && <p>{t('没有匹配的实验条件')}</p>}
      {visible.length > 50 && (
        <PageControls page={page} total={visible.length} onPage={setPage} disabled={false} />
      )}
    </fieldset>
  );
}
