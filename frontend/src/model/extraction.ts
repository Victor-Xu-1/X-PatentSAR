import { t } from '../i18n';
import type { Compound, Job, Stage, StageName } from '../api/types';
import { stageNames } from '../api/types';
import { stageLabels, stageStatusLabels } from './presentation';

export function pageProgressStage(name: StageName): boolean {
  return name === 'structures';
}

export function progressUnit(name: StageName): string {
  return pageProgressStage(name) ? t(' 页') : '';
}

export function stoppedJob(job: Job | null): boolean {
  return Boolean(job && job.status !== 'running' && job.status !== 'queued');
}

export function completeCoreStages(stages: Job['stages']): boolean {
  return stageNames.every((name) =>
    stages.some(
      (stage) =>
        stage.name === name &&
        (name === 'qa'
          ? stage.status === 'ok'
          : ['ok', 'empty', 'warnings'].includes(stage.status)),
    ),
  );
}

export function completedCoreRejection(job: Job | null): boolean {
  return Boolean(
    job?.history_available === true &&
    job.status === 'failed' &&
    job.error?.code === 'core_not_accepted' &&
    job.admet_only !== true &&
    stageNames.every((name) =>
      job.stages.some(
        (stage) =>
          stage.name === name && ['ok', 'empty', 'warnings', 'failed'].includes(stage.status),
      ),
    ) &&
    job.stages.some(
      (stage) => stage.name === 'qa' && ['failed', 'warnings'].includes(stage.status),
    ),
  );
}

export function recognitionReviewCount(job: Job | null): number | null {
  if (!completedCoreRejection(job)) return null;
  const stage = job!.stages.find((value) => value.name === 'smiles');
  const progress = stage?.progress;
  return stage?.status === 'failed' &&
    progress &&
    progress.total > 0 &&
    progress.completed === progress.total &&
    stage.count === progress.total &&
    progress.failures > 0 &&
    progress.failures <= progress.completed
    ? progress.failures
    : null;
}

export function reviewedCoreStage(job: Job | null, stage: Stage | undefined): boolean {
  return Boolean(
    stage?.status === 'failed' &&
    ['smiles', 'final', 'qa'].includes(stage.name) &&
    completedCoreRejection(job),
  );
}

export function stageProgressText(stage: Stage | undefined): string | null {
  const progress = stage?.progress;
  if (!stage || !progress) return null;
  return t(
    stage.status === 'failed'
      ? '已处理 {completed} / {total}{unit}'
      : '{completed} / {total}{unit}',
    { completed: progress.completed, total: progress.total, unit: progressUnit(stage.name) },
  );
}

export function workflowStageNames(job: Job | null): StageName[] {
  if (job?.admet_only === true) return ['admet'];
  return [
    ...(job?.stage_order ?? stageNames),
    ...(job?.include_admet === true ? ['admet' as const] : []),
  ];
}

export function waitingAdmet(job: Job | null, stage?: Stage): boolean {
  if (
    !job ||
    job.history_available !== true ||
    job.include_admet !== true ||
    job.admet_only ||
    stage
  )
    return false;
  if (!stageNames.every((name) => job.stages.some((value) => value.name === name))) return false;
  // This is the declared post-core dependency, not an invented producer fact.
  return (
    !completeCoreStages(job.stages) || !stoppedJob(job) || job.error?.code === 'core_not_accepted'
  );
}

export function observedStages(job: Job | null): Job['stages'] {
  if (job?.history_available !== true) return [];
  const order = workflowStageNames(job);
  const stages =
    job.admet_only === true
      ? []
      : job.stage_order
        ? [...job.stages].sort((a, b) => order.indexOf(a.name) - order.indexOf(b.name))
        : job.stages;
  const admet = job.include_admet === true ? job.admet_stage : null;
  if (!admet) return stages;
  // Terminal sealing can mark ADMET failed before its producer ever starts.
  const admetStarted =
    (admet.status !== 'pending' && admet.status !== 'failed') ||
    admet.count != null ||
    admet.duration_seconds != null ||
    admet.progress != null ||
    admet.resource_wait != null;
  const coreCompleted = completeCoreStages(stages) && job.error?.code !== 'core_not_accepted';
  return job.admet_only === true || admetStarted || coreCompleted ? [...stages, admet] : stages;
}

export function stageLabel(name: StageName, stage?: Stage): string {
  if (name === 'admet') {
    if (stage?.progress?.phase === 'recognition') return t('结构补齐');
    if (stage?.progress?.phase === 'properties') return t('指标计算');
    if (stage?.progress?.phase === 'lead') return t('Lead 筛选');
  }
  return t(stageLabels[name]);
}

export function waitingResources(job: Job | null, stage?: Stage): boolean {
  return Boolean(
    job?.history_available === true &&
    !stoppedJob(job) &&
    stage?.resource_wait != null &&
    (stage.status === 'running' || stage.status === 'pending'),
  );
}

export function stageStatusText(
  job: Job | null,
  stage: Job['stages'][number] | undefined,
  name?: StageName,
): string {
  if (job && job.history_available !== true)
    return job.history_available === false ? t('历史阶段不可用') : t('阶段状态未知');
  if (!stage) {
    if (name === 'admet' && waitingAdmet(job, stage))
      return stoppedJob(job) ? t('未执行') : t('等待');
    return job ? t('状态未提供') : t('尚未启动');
  }
  if (stoppedJob(job)) {
    if (stage.status === 'pending') return t('未执行');
    if (stage.status === 'running') return t('停止时进行中');
  }
  if (waitingResources(job, stage)) return t('等待资源');
  if (reviewedCoreStage(job, stage)) {
    if (stage.name === 'smiles') return t('需复核');
    if (stage.name === 'final') return t('未通过验收');
    if (stage.name === 'qa') return t('未通过');
  }
  return t(stageStatusLabels[stage.status]);
}

export function cropPlaceholder(compound: Compound): string {
  if (compound.flags.includes('image_unavailable')) return t('裁图文件缺失或不可访问');
  if (compound.flags.includes('structure_generation_failed')) return t('结构分割失败，未生成裁图');
  if (compound.flags.includes('structure_not_generated')) return t('尚未生成结构裁图');
  if (compound.flags.includes('structure_unmatched')) return t('尚未绑定结构裁图');
  return t('未提供结构裁图');
}
