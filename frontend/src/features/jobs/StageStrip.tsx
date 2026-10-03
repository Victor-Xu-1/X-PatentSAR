import { Check, CircleAlert, LoaderCircle } from 'lucide-react';
import type { Job } from '../../api/types';
import { stageNames } from '../../api/types';
import { stageLabels } from '../../model/presentation';
import { observedStages, stageStatusText, stoppedJob } from '../../model/extraction';
import { StageObservation } from './StageObservation';
export function StageStrip({ job, compact = false }: { job: Job | null; compact?: boolean }) {
  const stages = observedStages(job);
  return (
    <div className="stage-overview">
      {job && job.history_available !== true && (
        <output
          className="stage-history-notice"
          title={
            job.history_available === false
              ? '历史阶段不可用：旧任务使用共享目录，无法可靠还原本次阶段历史。'
              : '历史阶段可用性未知'
          }
        >
          {job.history_available === false
            ? compact
              ? '历史不可用'
              : '历史阶段不可用：旧任务使用共享目录，无法可靠还原本次阶段历史。'
            : '历史阶段可用性未知'}
        </output>
      )}
      <ol className="stage-strip" aria-label="真实提取流水线阶段">
        {stageNames.map((name, i) => {
          const stage = stages.find((item) => item.name === name);
          const status =
            job && job.history_available !== true ? 'unknown' : (stage?.status ?? 'pending');
          return (
            <li
              className={`stage ${status}`}
              key={name}
              title={`${stageLabels[name]}：${stageStatusText(job, stage)}`}
            >
              <span className="stage-circle">
                {status === 'ok' ? (
                  <Check size={13} />
                ) : status === 'running' && !stoppedJob(job) ? (
                  <LoaderCircle size={13} className="spin" />
                ) : status === 'failed' ? (
                  <CircleAlert size={13} />
                ) : (
                  i + 1
                )}
              </span>
              {job?.history_available === true ? (
                <StageObservation job={job} stage={stage} name={name} compact={compact} />
              ) : (
                <div>
                  <strong>{stageLabels[name]}</strong>
                  <small className={compact ? 'sr-only' : undefined}>
                    {stageStatusText(job, stage)}
                  </small>
                </div>
              )}
            </li>
          );
        })}
      </ol>
    </div>
  );
}
