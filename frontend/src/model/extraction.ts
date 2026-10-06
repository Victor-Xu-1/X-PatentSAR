import type { Compound, Job, Stage, StageName } from '../api/types';
import { stageNames } from '../api/types';
import { stageLabels, stageStatusLabels } from './presentation';

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
    if (stage?.progress?.phase === 'recognition') return '结构补齐';
    if (stage?.progress?.phase === 'properties') return '指标计算';
  }
  return stageLabels[name];
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
    return job.history_available === false ? '历史阶段不可用' : '阶段状态未知';
  if (!stage) {
    if (name === 'admet' && waitingAdmet(job, stage)) return stoppedJob(job) ? '未执行' : '等待';
    return job ? '状态未提供' : '尚未启动';
  }
  if (stoppedJob(job)) {
    if (stage.status === 'pending') return '未执行';
    if (stage.status === 'running') return '停止时进行中';
  }
  if (waitingResources(job, stage)) return '等待资源';
  return stageStatusLabels[stage.status];
}

export function cropPlaceholder(compound: Compound): string {
  if (compound.flags.includes('image_unavailable')) return '裁图文件缺失或不可访问';
  if (compound.flags.includes('structure_generation_failed')) return '结构分割失败，未生成裁图';
  if (compound.flags.includes('structure_not_generated')) return '尚未生成结构裁图';
  if (compound.flags.includes('structure_unmatched')) return '尚未绑定结构裁图';
  return '未提供结构裁图';
}
