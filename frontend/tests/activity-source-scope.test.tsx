import { render, screen } from '@testing-library/react';
import { describe, expect, it } from 'vitest';
import { decodeActivityScope } from '../src/api/activityScopeDecoders';
import { activityContextKey, decodeActivityColumns } from '../src/api/activityColumnDecoders';
import { activityDecoder } from '../src/api/decoders';
import { decodeEditableFields } from '../src/api/correctionDecoders';
import { decodeDataset } from '../src/api/sarDecoders';
import { studyContext as decodeContext } from '../src/api/sarStudyRowDecoders';
import { activityColumnObservations } from '../src/model/activityColumns';
import { contextLabel } from '../src/features/sar/presentation';
import { ContextPicker } from '../src/features/sar/study/ContextPicker';
import { correctionDraft, draftFields } from '../src/features/results/correctionDraft';
import { setLocale } from '../src/i18n';
import { compound } from './fixtures';
import { sarDataset, studyContext } from './sar-fixtures';

const scope = (table: number) => ({
  source_scope: String(table).repeat(64),
  source_table: `Table ${table}`,
  source_context_page: 1,
  source_conditions: { cell_line: 'HEK293', duration: '24 h' },
});
const activity = { name: 'IC50', value: '1', unit: 'nM', target: 'T', assay: 'binding', page: 1 };

describe('original experimental scope through read contracts and presentation', () => {
  it('preserves legacy identities and separates identical labels in original tables', () => {
    expect(activityContextKey(activity)).toBe(JSON.stringify(['IC50', 'nM', 'T', 'binding']));
    const values = [1, 2].map((table) => activityDecoder({ ...activity, ...scope(table) }));
    const columns = decodeActivityColumns(
      values.map((item, index) => ({ ...item, id: String(index + 3).repeat(64) })),
    );
    expect(activityContextKey(values[0]!)).not.toBe(activityContextKey(values[1]!));
    const groups = activityColumnObservations({ ...compound, activities: values }, columns);
    expect(groups.map((items) => items.length)).toEqual([1, 1]);
    expect(groups[1]![0]!.activity.source_table).toBe('Table 2');
  });

  it('retains scope on correction round trips and SAR metric/context transport', () => {
    const input = { ...activity, ...scope(1) };
    const fields = decodeEditableFields({
      display_id: '1',
      smiles: null,
      structure_molfile: null,
      activities: [input],
    });
    expect(fields.activities[0]!.source_scope).toBe(input.source_scope);
    expect(fields.activities[0]!.source_conditions).toEqual(input.source_conditions);
    const dataset = decodeDataset({
      ...sarDataset,
      metrics: [{ ...sarDataset.metrics[0], ...scope(1) }],
    });
    expect(dataset.metrics[0]!.source_table).toBe('Table 1');
    expect(dataset.metrics[0]!.source_conditions).toEqual(input.source_conditions);
    expect(decodeContext({ ...studyContext, ...scope(1) }).source_scope).toBe(input.source_scope);
  });

  it('rejects malformed or orphan scope metadata rather than dropping it', () => {
    for (const fields of [
      null,
      [],
      { source_scope: 'bad', source_context_page: 1 },
      { source_table: 'Table 1' },
      { source_scope: '1'.repeat(64) },
      { ...scope(1), source_context_page: true },
      { ...scope(1), source_context_page: 20001 },
      { ...scope(1), source_scope: '1'.repeat(64) + '\n' },
      { ...scope(1), source_conditions: { unknown: 'X' } },
      { ...scope(1), source_conditions: { cell_line: 'a\0b' } },
      { source_conditions: { cell_line: 'HEK293' } },
    ])
      expect(() => decodeActivityScope(fields)).toThrow();
    expect(decodeActivityScope({})).toEqual({});
  });

  it('copies an existing original column without changing its conditions or source', () => {
    const columns = decodeActivityColumns([{ ...activity, ...scope(1), id: 'a'.repeat(64) }]);
    const draft = correctionDraft(
      { display_id: '1', smiles: null, structure_molfile: null, activities: [] },
      undefined,
      columns,
    );
    expect(draft.activities[0]!.source.source_conditions).toEqual(scope(1).source_conditions);
    draft.activities[0]!.value = '2';
    const saved = draftFields(draft).activities[0]!;
    expect(saved.source_scope).toBe(scope(1).source_scope);
    expect(saved.source_conditions).toEqual(scope(1).source_conditions);
    expect(saved.page).toBeNull(); // A manual entry does not invent an original row.
  });

  it.each(['en', 'zh-CN'] as const)(
    'shows literal source labels, never opaque IDs in %s',
    (locale) => {
      setLocale(locale);
      const contexts = [1, 2].map((table) => ({
        ...studyContext,
        ...scope(table),
        id: String(table + 3).repeat(64),
      }));
      const view = render(
        <ContextPicker contexts={contexts} selected={[]} onSelect={() => undefined} />,
      );
      expect(screen.getByText(contextLabel(contexts[0]!))).toHaveTextContent('Table 1 · p. 1');
      expect(screen.getByText(contextLabel(contexts[1]!))).toHaveTextContent('Table 2 · p. 1');
      expect(view.container.textContent).not.toContain('1'.repeat(64));
      view.unmount();
    },
  );
});
