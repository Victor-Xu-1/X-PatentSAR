import type { Job, Stage, StageName } from '../api/types';
import { t } from '../i18n';
import {
  observedStages,
  reviewedCoreStage,
  stageLabel,
  stageStatusText,
  stoppedJob,
  waitingAdmet,
  workflowStageNames,
} from './extraction';

export type WorkflowGroupState = Stage['status'] | 'review' | 'stopped' | 'unknown';
export interface WorkflowGroup {
  key: string;
  label: string;
  compactLabel: string;
  names: StageName[];
  state: WorkflowGroupState;
  description: string;
}

const sections = {
  source: { label: '解析定位', compactLabel: '解析' },
  structure: { label: '结构编号', compactLabel: '结构' },
  recognition: { label: '活性识别', compactLabel: '活性' },
  delivery: { label: '校验与指标', compactLabel: '校验' },
} as const;
const sectionKeys: Record<StageName, keyof typeof sections> = {
  classify: 'source',
  locate: 'source',
  structures: 'structure',
  bind: 'structure',
  activity: 'recognition',
  smiles: 'recognition',
  final: 'delivery',
  qa: 'delivery',
  admet: 'delivery',
};

export const workflowGroupStateText: Record<WorkflowGroupState, string> = {
  ok: '已完成',
  empty: '无数据',
  warnings: '有警告',
  review: '需复核',
  running: '进行中',
  stopped: '停止时未完成',
  failed: '失败',
  pending: '等待',
  unknown: '状态未知',
};

function groupState(job: Job | null, names: StageName[], stages: Stage[]): WorkflowGroupState {
  if (!job) return 'pending';
  if (job.history_available !== true) return 'unknown';
  const values = names.map((name) => stages.find((stage) => stage.name === name));
  if (values.some((stage) => stage?.status === 'failed' && !reviewedCoreStage(job, stage)))
    return 'failed';
  if (values.some((stage) => reviewedCoreStage(job, stage))) return 'review';
  if (values.some((stage) => stage?.status === 'running'))
    return stoppedJob(job) ? 'stopped' : 'running';
  if (values.some((stage) => stage?.status === 'warnings')) return 'warnings';
  if (
    values.some((stage, index) => !stage && !(names[index] === 'admet' && waitingAdmet(job, stage)))
  )
    return 'unknown';
  if (values.some((stage) => !stage || stage.status === 'pending')) return 'pending';
  if (values.every((stage) => stage?.status === 'empty')) return 'empty';
  return 'ok';
}

/** Consecutive presentation groups preserve the recorded order, including legacy orders. */
export function workflowGroups(job: Job | null): WorkflowGroup[] {
  const stages = observedStages(job);
  const groups: WorkflowGroup[] = [];
  for (const name of workflowStageNames(job)) {
    const key = sectionKeys[name];
    const section = sections[key];
    const previous = groups.at(-1);
    if (previous?.key.startsWith(`${key}:`)) previous.names.push(name);
    else
      groups.push({
        key: `${key}:${groups.length}`,
        label: job?.admet_only
          ? t(
              stageLabel(
                name,
                stages.find((stage) => stage.name === name),
              ),
            )
          : t(section.label),
        compactLabel: job?.admet_only
          ? t(
              stageLabel(
                name,
                stages.find((stage) => stage.name === name),
              ),
            )
          : t(section.compactLabel),
        names: [name],
        state: 'unknown',
        description: '',
      });
  }
  return groups.map((group) => ({
    ...group,
    state: groupState(job, group.names, stages),
    description: group.names
      .map((name) => {
        const stage = stages.find((value) => value.name === name);
        return t('{label}：{state}', {
          label: t(stageLabel(name, stage)),
          state: t(stageStatusText(job, stage, name)),
        });
      })
      .join(t('；')),
  }));
}
