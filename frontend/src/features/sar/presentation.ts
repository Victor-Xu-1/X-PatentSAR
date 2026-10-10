import { emptyRoute, routeHash } from '../../model/route';
import type { Comparison, Dataset, JobState, MatchState, Molecule, Pair } from '../../api/sarTypes';

export const jobLabels: Record<JobState, string> = {
  queued: 'SAR 排队中',
  running: 'SAR 运行中',
  complete: 'SAR 已完成',
  failed: 'SAR 失败',
  cancelled: 'SAR 已取消',
  interrupted: 'SAR 已中断',
};
export const matchLabels: Record<MatchState, string> = {
  matched: 'SAR 匹配',
  not_matched: 'SAR 未匹配',
  ambiguous: 'SAR 歧义',
  ineligible: 'SAR 不合格',
};
export const comparisonLabels: Record<Comparison, string> = {
  better: 'SAR 更强',
  worse: 'SAR 更弱',
  equal: 'SAR 相同',
  indeterminate: 'SAR 无法确定',
  missing: 'SAR 缺失',
  context_mismatch: 'SAR 条件不同',
};
export const evidenceLabels: Record<Pair['evidence_basis'], string> = {
  recorded_context: '记录条件',
  user_confirmed: '用户确认缺失条件',
  source_declared: '原文条件人工记录',
  insufficient: '证据不足',
};
export const isActiveJob = (job: { status: JobState }) =>
  ['queued', 'running'].includes(job.status);
export function sourceHash(dataset: Dataset, molecule?: Molecule, page: number | null = null) {
  if (!dataset.source_project_id) return null;
  return routeHash({
    ...emptyRoute,
    view: 'workspace',
    projectId: dataset.source_project_id,
    compoundId: molecule?.source_compound_id ?? null,
    page,
  });
}
export const newRequestId = () => crypto.randomUUID().replaceAll('-', '');
/** One display-only label rule; source names/units and values remain unchanged. */
export const contextLabel = (context: { name: string; unit: string | null }) =>
  context.unit &&
  !context.name.endsWith('(' + context.unit + ')') &&
  !context.name.endsWith(' ' + context.unit)
    ? context.name + ' · ' + context.unit
    : context.name;
export function gradeOrder(text: string) {
  const values = text
    .split(/\r?\n/)
    .map((value) => value.trim())
    .filter(Boolean);
  return { values, valid: values.length <= 32 && new Set(values).size === values.length };
}
