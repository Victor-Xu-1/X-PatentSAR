import type { Job } from '../../api/types';
import { ChevronDown } from 'lucide-react';
import { dateText } from '../../model/presentation';
import { jobRecordSummary } from '../../model/jobPresentation';
import { StageStrip } from './StageStrip';

export function JobRecord({ job, expanded = false }: { job: Job; expanded?: boolean }) {
  const summary = jobRecordSummary(job);
  return (
    <>
      {summary && <p className={`job-summary${job.error ? ' has-error' : ''}`}>{summary}</p>}
      <details className="job-options-record job-record" open={expanded ? true : undefined}>
        <summary aria-label="任务详情">
          任务详情
          <ChevronDown size={14} aria-hidden="true" />
        </summary>
        <div className="job-record-body">
          <dl className="job-dates">
            {(
              [
                ['创建', job.created_at],
                ['开始', job.started_at],
                ['结束', job.finished_at],
              ] as const
            ).map(([label, value]) => (
              <div key={label}>
                <dt>{label}</dt>
                <dd>{value ? <time dateTime={value}>{dateText(value)}</time> : '—'}</dd>
              </div>
            ))}
          </dl>
          <StageStrip job={job} />
          {job.error && (
            <section className="job-failure-details" aria-label="失败详情">
              <h3>失败详情</h3>
              <output className="job-error">
                {job.error.code}：{job.error.message}
              </output>
            </section>
          )}
          <section className="job-saved-options" aria-label="已保存的任务参数">
            <h3>已保存的任务参数</h3>
            <dl>
              <div>
                <dt>包含中间体</dt>
                <dd>{job.include_intermediates ? '是' : '否'}</dd>
              </div>
              <div>
                <dt>强制重算</dt>
                <dd>{job.force ? '是' : '否'}</dd>
              </div>
              <div>
                <dt>运营备注（不执行）</dt>
                <dd>{job.task_note || '无'}</dd>
              </div>
            </dl>
            {job.can_resume && <p>续跑保留原备注及中间体选项，不强制重算。</p>}
          </section>
          <small className="job-identifier" title={job.id}>
            任务 {job.id}
          </small>
        </div>
      </details>
    </>
  );
}
