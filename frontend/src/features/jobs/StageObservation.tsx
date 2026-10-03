import type { Job, StageName } from '../../api/types';
import { stageLabels } from '../../model/presentation';
import { stageStatusText } from '../../model/extraction';

export function StageObservation({
  job,
  stage,
  name,
  compact = false,
}: {
  job: Job;
  stage: Job['stages'][number] | undefined;
  name: StageName;
  compact?: boolean;
}) {
  const progress = stage?.progress;
  return (
    <details className="stage-observation" name={`stage-observations-${job.id}`}>
      <summary
        title={`${stageLabels[name]}：${stageStatusText(job, stage)}${stage?.count == null ? '' : ` · ${stage.count}`}`}
      >
        <strong>{stageLabels[name]}</strong>
        {compact ? (
          progress && progress.total > 0 && stage?.status === 'running' ? (
            <small className="stage-progress">
              {progress.completed} / {progress.total}
            </small>
          ) : null
        ) : (
          <small>
            <span>{stageStatusText(job, stage)}</span>
            {stage?.count != null && ` · ${stage.count}`}
            {progress && (
              <span className="stage-progress">
                {' · '}
                {progress.completed} / {progress.total}
              </span>
            )}
            {stage?.reused_checkpoint === true && <span> · 复用检查点</span>}
          </small>
        )}
      </summary>
      <div className="stage-observation-detail">
        {compact && (
          <p>
            {stageStatusText(job, stage)}
            {stage?.count == null ? '' : ` · ${stage.count}`}
          </p>
        )}
        {!progress ? (
          <p>进度未提供</p>
        ) : (
          <>
            <p>
              缓存命中 {progress.cache_hits} · 失败 {progress.failures}
            </p>
            <p>
              {progress.device === null ? '执行设备未知' : progress.device.toUpperCase()}
              {' · '}
              {progress.peak_rss_mb === null
                ? '峰值 RSS 未提供'
                : `峰值 RSS ${progress.peak_rss_mb} MB`}
            </p>
          </>
        )}
        {stage?.reused_checkpoint == null && <p>检查点复用未知</p>}
        {name === 'admet' && stage?.skipped != null && stage.skipped > 0 && (
          <p>未计算 {stage.skipped}（缺少有效SMILES）</p>
        )}
        {stage?.reused_checkpoint === false && <p>本次执行，未复用检查点</p>}
        <p className="muted">只展示服务端观察，不推算准确率、百分比或剩余时间。</p>
      </div>
    </details>
  );
}
