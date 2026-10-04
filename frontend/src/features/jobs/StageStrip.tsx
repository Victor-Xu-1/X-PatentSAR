import { Check, CircleAlert, LoaderCircle } from 'lucide-react';
import type { Job, StageName } from '../../api/types';
import { stageNames } from '../../api/types';
import { jobStatusLabels } from '../../model/presentation';
import { observedStages, stageLabel, stageStatusText, stoppedJob } from '../../model/extraction';
import { StageObservation } from './StageObservation';

export function StageStrip({ job, compact = false }: { job: Job | null; compact?: boolean }) {
  const stages = observedStages(job);
  const names: StageName[] =
    job?.admet_only === true
      ? stages.map((stage) => stage.name)
      : [
          ...stageNames,
          ...(stages.some((stage) => stage.name === 'admet') ? ['admet' as const] : []),
        ];
  const historyNotice =
    job && job.history_available !== true ? (
      <output className="stage-history-notice">
        {job.history_available === false
          ? '历史阶段不可用：旧任务使用共享目录，无法可靠还原本次阶段历史。'
          : '历史阶段可用性未知'}
      </output>
    ) : null;
  const list = (
    <ol className="stage-strip" aria-label="真实提取流水线阶段">
      {names.map((name, index) => {
        const stage = stages.find((item) => item.name === name);
        const label = stageLabel(name, stage);
        const status =
          job && job.history_available !== true ? 'unknown' : (stage?.status ?? 'pending');
        return (
          <li
            className={`stage ${status}`}
            key={name}
            title={`${label}：${stageStatusText(job, stage)}`}
          >
            <span className="stage-circle">
              {status === 'ok' ? (
                <Check size={13} />
              ) : status === 'running' && !stoppedJob(job) ? (
                <LoaderCircle size={13} className="spin" />
              ) : status === 'failed' ? (
                <CircleAlert size={13} />
              ) : (
                index + 1
              )}
            </span>
            {job?.history_available === true ? (
              <StageObservation job={job} stage={stage} name={name} />
            ) : (
              <div>
                <strong>{label}</strong>
                <small>{stageStatusText(job, stage)}</small>
              </div>
            )}
          </li>
        );
      })}
    </ol>
  );
  if (!compact)
    return (
      <div className="stage-overview">
        {historyNotice}
        {list}
      </div>
    );

  const current =
    stages.find((stage) => stage.status === 'failed') ??
    stages.find((stage) => stage.status === 'running') ??
    stages.find((stage) => stage.status === 'pending') ??
    stages.at(-1);
  const label = !job
    ? '尚未启动'
    : job.history_available !== true
      ? job.history_available === false
        ? '历史阶段不可用'
        : '阶段状态未知'
      : job.status === 'complete'
        ? current?.name === 'admet' && current.status === 'empty'
          ? `${stageLabel(current.name, current)} · 未计算`
          : jobStatusLabels[job.status]
        : current
          ? `${stageLabel(current.name, current)} · ${stageStatusText(job, current)}`
          : jobStatusLabels[job.status];
  const progress = current?.progress;
  return (
    <details className="stage-overview stage-disclosure">
      <summary className="stage-current-line" aria-label="提取阶段详情">
        <output className="stage-current" aria-live="polite" style={{ display: 'inline' }}>
          {label}
          {progress && progress.total > 0 && (
            <span className="stage-progress">
              {' '}
              · {progress.completed} / {progress.total}
            </span>
          )}
        </output>
      </summary>
      {historyNotice}
      {list}
    </details>
  );
}
