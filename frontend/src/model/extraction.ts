import type { Compound, Job } from '../api/types';
import { stageStatusLabels } from './presentation';

export function stoppedJob(job: Job | null): boolean {
  return Boolean(job && job.status !== 'running' && job.status !== 'queued');
}

export function stageStatusText(job: Job | null, stage: Job['stages'][number] | undefined): string {
  if (!stage) return job ? '状态未提供' : '尚未启动';
  if (stoppedJob(job)) {
    if (stage.status === 'pending') return '未执行';
    if (stage.status === 'running') return '停止时进行中';
  }
  return stageStatusLabels[stage.status];
}

export function cropPlaceholder(compound: Compound): string {
  if (compound.flags.includes('image_unavailable')) return '裁图文件缺失或不可访问';
  if (compound.flags.includes('structure_generation_failed')) return '结构分割失败，未生成裁图';
  if (compound.flags.includes('structure_not_generated')) return '尚未生成结构裁图';
  if (compound.flags.includes('structure_unmatched')) return '尚未绑定结构裁图';
  return '未提供结构裁图';
}
