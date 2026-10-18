import type {
  AcceptanceState,
  Activity,
  ConfidenceLevel,
  Job,
  ReviewDecision,
  StageName,
  StageStatus,
} from '../api/types';
import { getLocale, t } from '../i18n';
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
export function jobStatusText(job: Job): string {
  return t(
    job.status === 'failed' && job.error?.code === 'core_not_accepted'
      ? '需复核'
      : jobStatusLabels[job.status],
  );
}
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
const confidenceReasons: Record<string, string> = {
  '已保留结构原图；尚未证实原文编号，不能猜测或按活性集合分配编号。':
    '原图已保留，原文编号待核验。',
  'Historical artifact identity; not current confirmation.': '历史结果，尚未按当前规则核验。',
  'Current core binding evidence.': '当前核心绑定证据。',
  'Core binding requires review.': '核心绑定需复核。',
  'No unique current core binding evidence.': '未提供唯一的当前核心绑定证据。',
};

/** Only known application-owned status copy is localized; unknown content stays literal. */
export function confidenceReasonText(reason: string | null | undefined): string {
  if (!reason) return t('依据未提供');
  return Object.hasOwn(confidenceReasons, reason) ? t(confidenceReasons[reason]!) : reason;
}
export const reviewLabels: Record<ReviewDecision, string> = {
  approved: '复核通过',
  rejected: '复核不通过',
  needs_review: '待复核',
};
export const activeJob = (job: Job) => job.status === 'running' || job.status === 'queued';
export function activityValueText(activity: Activity): string {
  const value = activity.value === null ? t('值未提供') : String(activity.value);
  const unit = activity.unit?.trim() ?? '';
  const escaped = unit.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
  const alreadyPresent =
    unit !== '' && new RegExp(`(?:^|[^\\p{L}])${escaped}\\s*$`, 'u').test(value);
  const suffix = unit && activity.value !== null && !alreadyPresent ? ` ${unit}` : '';
  return `${value}${suffix}`;
}
export function activityText(activity: Activity): string {
  return `${activity.name || t('活性')} = ${activityValueText(activity)}`;
}
export function dateText(value: string | null): string {
  if (!value) return '—';
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? value : date.toLocaleString(getLocale(), { hour12: false });
}
