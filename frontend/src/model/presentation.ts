import type {
  AcceptanceState,
  Activity,
  ConfidenceLevel,
  Job,
  ReviewDecision,
  StageName,
  StageStatus,
} from '../api/types';
export const stageLabels: Record<StageName, string> = {
  classify: '文档解析',
  activity: '活性提取',
  locate: '结构定位',
  structures: '结构分割',
  bind: '编号绑定',
  smiles: 'SMILES 识别',
  final: '生成结果',
  qa: '核心校验',
  admet: 'ADMET / 指标',
};
export const stageStatusLabels: Record<StageStatus, string> = {
  pending: '等待',
  running: '进行中',
  ok: '完成',
  empty: '无数据',
  failed: '失败',
  warnings: '有警告',
};
export const jobStatusLabels: Record<Job['status'], string> = {
  queued: '排队中',
  running: '运行中',
  complete: '运行完成',
  failed: '运行失败',
  cancelled: '已取消',
  interrupted: '已中断',
};
export const acceptanceLabels: Record<AcceptanceState, string> = {
  not_run: '尚未验收',
  accepted: '核心 QA 通过',
  failed: '提取未通过验收',
  historical: '历史结果 · 仅供复核',
};
export const confidenceLabels: Record<ConfidenceLevel, string> = {
  high: '高',
  medium: '中',
  review: '待核验',
  unknown: '未知',
};
export const reviewLabels: Record<ReviewDecision, string> = {
  approved: '复核通过',
  rejected: '复核不通过',
  needs_review: '待复核',
};
export const activeJob = (job: Job) => job.status === 'running' || job.status === 'queued';
export function activityValueText(activity: Activity): string {
  const value = activity.value === null ? '值未提供' : String(activity.value);
  const unit = activity.unit?.trim() ?? '';
  const escaped = unit.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
  const alreadyPresent =
    unit !== '' && new RegExp(`(?:^|[^\\p{L}])${escaped}\\s*$`, 'u').test(value);
  const suffix = unit && activity.value !== null && !alreadyPresent ? ` ${unit}` : '';
  return `${value}${suffix}`;
}
export function activityText(activity: Activity): string {
  return `${activity.name || '活性'} = ${activityValueText(activity)}`;
}
export function dateText(value: string | null): string {
  if (!value) return '—';
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? value : date.toLocaleString('zh-CN', { hour12: false });
}
