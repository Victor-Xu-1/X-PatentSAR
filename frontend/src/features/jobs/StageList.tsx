import { Check, CircleAlert, LoaderCircle } from 'lucide-react';
import type { Job, StageName } from '../../api/types';
import {
  reviewedCoreStage,
  stageLabel,
  stageStatusText,
  stoppedJob,
  waitingAdmet,
} from '../../model/extraction';
import { StageObservation } from './StageObservation';

export function StageList({
  job,
  stages,
  names,
}: {
  job: Job | null;
  stages: Job['stages'];
  names: StageName[];
}) {
  return (
    <ol className="stage-strip" aria-label="任务运行链路">
      {names.map((name, index) => {
        const stage = stages.find((item) => item.name === name);
        const label = stageLabel(name, stage);
        const status =
          job && job.history_available !== true
            ? 'unknown'
            : (stage?.status ??
              (name === 'admet' && !waitingAdmet(job, stage) ? 'unknown' : 'pending'));
        return (
          <li
            className={`stage ${status}${reviewedCoreStage(job, stage) ? ' needs-review' : ''}`}
            key={name}
            title={`${label}：${stageStatusText(job, stage, name)}`}
          >
            <span className="stage-circle" aria-hidden="true">
              {status === 'ok' ? (
                <Check size={14} />
              ) : status === 'running' && !stoppedJob(job) ? (
                <LoaderCircle size={14} className="spin" />
              ) : status === 'failed' ? (
                <CircleAlert size={14} />
              ) : (
                index + 1
              )}
            </span>
            {job?.history_available === true ? (
              <StageObservation job={job} stage={stage} name={name} />
            ) : (
              <div>
                <strong>{label}</strong>
                <small>{stageStatusText(job, stage, name)}</small>
              </div>
            )}
          </li>
        );
      })}
    </ol>
  );
}
