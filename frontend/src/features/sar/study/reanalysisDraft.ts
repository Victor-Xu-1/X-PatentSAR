import type { CatalogReport } from '../../../api/sarCatalogTypes';
import type { Dataset } from '../../../api/sarTypes';

import { UiError } from '../../../i18n';
import { gradeOrder } from '../presentation';
import { declarationFromDraft } from './conditionDraft';
import type { ConditionDraft } from './conditionDraft';
import type { PolicyDraft } from './policyDraft';

/** Only form state. Submission still belongs to StudySetup and the existing API. */
export interface StudySetupSeed {
  owner: string;
  title: string;
  selected: string[];
  policies: Record<string, PolicyDraft>;
  conditions: Record<string, ConditionDraft>;
}
export const datasetDraftOwner = (dataset: Dataset) =>
  JSON.stringify([
    dataset.id,
    dataset.revision,
    dataset.source_sha256,
    dataset.source_document_sha256 ?? null,
  ]);

const sameFields = (a: Record<string, string>, b: Record<string, string>) =>
  JSON.stringify(Object.entries(a).sort()) === JSON.stringify(Object.entries(b).sort());

export function reanalysisDraft(dataset: Dataset, report: CatalogReport): StudySetupSeed {
  const fail = () => new UiError('无法安全沿用这份报告的设置。请刷新数据集后核对指标与原文条件。');
  if (
    dataset.stale ||
    report.dataset_id !== dataset.id ||
    report.dataset_revision !== dataset.revision ||
    report.policies.length < 1 ||
    report.policies.length > 8
  )
    throw fail();
  const contexts = new Map(report.contexts.map((context) => [context.id, context]));
  const selected = report.policies.map((policy) => policy.context_id);
  if (new Set(selected).size !== selected.length || selected.some((id) => !contexts.has(id)))
    throw fail();
  const policies: Record<string, PolicyDraft> = {};
  for (const policy of report.policies) {
    const grades = policy.grade_order.join('\n');
    const parsed = gradeOrder(grades);
    if (!parsed.valid || JSON.stringify(parsed.values) !== JSON.stringify(policy.grade_order))
      throw fail();
    policies[policy.context_id] = { direction: policy.direction, grades };
  }
  const conditions: Record<string, ConditionDraft> = {};
  for (const declaration of report.context_declarations ?? []) {
    const context = contexts.get(declaration.context_id);
    if (
      !context ||
      !selected.includes(declaration.context_id) ||
      conditions[declaration.context_id]
    )
      throw fail();
    const draft: ConditionDraft = {
      enabled: true,
      fields: { ...declaration.fields },
      pages: declaration.source_pages.join(', '),
      note: declaration.note,
    };
    const checked = declarationFromDraft(dataset, context, draft);
    if (
      !checked ||
      checked.source_document_sha256 !== declaration.source_document_sha256 ||
      checked.note !== declaration.note ||
      !sameFields(checked.fields, declaration.fields) ||
      JSON.stringify(checked.source_pages) !== JSON.stringify(declaration.source_pages)
    )
      throw fail();
    conditions[declaration.context_id] = draft;
  }
  // No captured request ID, fixed potency threshold, confirmation, region/core
  // selection or result is copied. Current policies and discovery remain owned
  // by the normal new-study form and independently validated by the server.
  return { owner: datasetDraftOwner(dataset), title: report.title, selected, policies, conditions };
}
