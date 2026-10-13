import { describe, expect, it } from 'vitest';
import { reanalysisDraft, datasetDraftOwner } from '../src/features/sar/study/reanalysisDraft';
import { sarDataset, studyContext, studyReport } from './sar-fixtures';

const dataset = { ...sarDataset, source_page_count: 20 };
const context = { ...studyContext, context: { ...studyContext.context, duration: null } };
const declaration = {
  context_id: context.id,
  fields: { duration: '2 h' },
  source_pages: [3, 4],
  source_document_sha256: dataset.source_document_sha256!,
  note: '原文条件 checked · preserve this source note',
};
const report = { ...studyReport, contexts: [context], context_declarations: [declaration] };

describe('source-bound reanalysis draft, not a second submission policy', () => {
  it('copies only exact editable settings and leaves original records untouched', () => {
    const before = JSON.stringify(report);
    const seed = reanalysisDraft(dataset, report);
    expect(seed.owner).toBe(datasetDraftOwner(dataset));
    expect(seed.title).toBe(report.title);
    expect(seed.selected).toEqual([context.id]);
    expect(seed.policies[context.id]).toEqual({ direction: 'lower', grades: '' });
    expect(seed.conditions[context.id]).toEqual({
      enabled: true,
      fields: { duration: '2 h' },
      pages: '3, 4',
      note: declaration.note,
    });
    expect(seed).not.toHaveProperty('request_id');
    expect(seed).not.toHaveProperty('region_ids');
    expect(seed).not.toHaveProperty('core_ids');
    expect(seed).not.toHaveProperty('confirm_context');
    seed.conditions[context.id]!.fields.duration = '99 h';
    seed.selected.push('another');
    expect(JSON.stringify(report)).toBe(before);
  });

  it('keeps source grades lossless, including commas, without carrying a numeric threshold', () => {
    const grades = ['A, strong 原文', 'B;weak'];
    const seed = reanalysisDraft(dataset, {
      ...report,
      policies: [{ ...report.policies[0]!, grade_order: grades, strong_threshold: 123 }],
    });
    expect(seed.policies[context.id]!.grades).toBe(grades.join('\n'));
    expect(seed.policies[context.id]).not.toHaveProperty('strong_threshold');
    expect(() =>
      reanalysisDraft(dataset, {
        ...report,
        policies: [{ ...report.policies[0]!, grade_order: ['A\nB'] }],
      }),
    ).toThrow();
  });

  it.each([
    { ...dataset, stale: true },
    { ...dataset, id: 'another' },
    { ...dataset, revision: dataset.revision + 1 },
    { ...dataset, source_document_sha256: '7'.repeat(64) },
    { ...dataset, source_kind: 'csv' as const },
    { ...dataset, source_page_count: 2 },
  ])('refuses stale, foreign or unprovable condition ownership', (changed) => {
    expect(() => reanalysisDraft(changed, report)).toThrow();
  });

  it('refuses incomplete or conflicting saved selections rather than silently dropping them', () => {
    for (const changed of [
      { ...report, policies: [] },
      { ...report, contexts: [] },
      { ...report, policies: [...report.policies, ...report.policies] },
      { ...report, contexts: [{ ...context, context: { ...context.context, duration: 'other' } }] },
      { ...report, context_declarations: [{ ...declaration, context_id: 'f'.repeat(64) }] },
      { ...report, context_declarations: [declaration, declaration] },
    ])
      expect(() => reanalysisDraft(dataset, changed)).toThrow();
  });
});
