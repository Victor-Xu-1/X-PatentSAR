import type { Dataset } from '../../../api/sarTypes';
import type { ConditionDeclaration, StudyContext } from '../../../api/sarStudyTypes';

export const conditionFields = ['target', 'assay', 'cell_line', 'duration'] as const;
export const missingCondition = (value: string | null | undefined) =>
  value == null ||
  ['', 'unknown', 'not recorded', 'not specified'].includes(value.trim().toLowerCase());
export interface ConditionDraft {
  enabled: boolean;
  fields: Partial<Record<(typeof conditionFields)[number], string>>;
  pages: string;
  note: string;
}
export const emptyCondition = (): ConditionDraft => ({
  enabled: false,
  fields: {},
  pages: '',
  note: '',
});
export function declarationFromDraft(
  dataset: Dataset,
  context: StudyContext,
  draft: ConditionDraft,
): ConditionDeclaration | null {
  if (
    !draft.enabled ||
    dataset.source_kind !== 'project' ||
    !dataset.source_document_sha256 ||
    !dataset.source_page_count
  )
    return null;
  const fields = Object.fromEntries(
    conditionFields
      .filter((key) => missingCondition(context.context[key]) && Boolean(draft.fields[key]?.trim()))
      .map((key) => [key, draft.fields[key]!.trim()]),
  );
  const tokens = draft.pages.trim().split(/[,，\s]+/);
  if (!tokens.length || tokens.some((token) => !/^\d{1,5}$/.test(token))) return null;
  const pages = tokens.map(Number);
  if (
    !Object.keys(fields).length ||
    Object.values(fields).some((value) => value.length > 1000 || missingCondition(value)) ||
    pages.length > 12 ||
    new Set(pages).size !== pages.length ||
    pages.some((page) => page < 1 || page > dataset.source_page_count!) ||
    !draft.note.trim() ||
    draft.note.length > 2000
  )
    return null;
  return {
    context_id: context.id,
    fields,
    source_pages: pages,
    note: draft.note.trim(),
    source_document_sha256: dataset.source_document_sha256,
  };
}
