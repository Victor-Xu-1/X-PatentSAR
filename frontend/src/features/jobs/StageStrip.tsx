import { Check, CircleAlert, LoaderCircle } from 'lucide-react';
import type { Job } from '../../api/types';
import { stageNames } from '../../api/types';
import { stageLabels, stageStatusLabels } from '../../model/presentation';
export function StageStrip({ job }: { job: Job | null }) {
  return (
    <ol className="stage-strip" aria-label="真实提取流水线阶段">
      {stageNames.map((name, i) => {
        const stage = job?.stages.find((item) => item.name === name);
        const status = stage?.status ?? 'pending';
        return (
          <li className={`stage ${status}`} key={name}>
            <span className="stage-circle">
              {status === 'ok' ? (
                <Check size={13} />
              ) : status === 'running' ? (
                <LoaderCircle size={13} className="spin" />
              ) : status === 'failed' ? (
                <CircleAlert size={13} />
              ) : (
                i + 1
              )}
            </span>
            <div>
              <strong>{stageLabels[name]}</strong>
              <small>
                {stage ? stageStatusLabels[status] : job ? '状态未提供' : '尚未启动'}
                {stage?.count !== null && stage?.count !== undefined ? ` · ${stage.count}` : ''}
              </small>
            </div>
          </li>
        );
      })}
    </ol>
  );
}
