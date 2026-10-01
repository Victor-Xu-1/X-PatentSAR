import type { Job } from '../../api/types';

export function JobRecord({ job, expanded = false }: { job: Job; expanded?: boolean }) {
  return (
    <>
      {job.error && (
        <output className="job-error">
          {job.error.code}：{job.error.message}
        </output>
      )}
      <details className="job-options-record" open={expanded ? true : undefined}>
        <summary>已保存的任务参数</summary>
        <p>
          包含中间体：{job.include_intermediates ? '是' : '否'} · 强制重算：
          {job.force ? '是' : '否'}
        </p>
        <p>运营备注（不执行）：{job.task_note || '无'}</p>
        {job.can_resume && <p>恢复保留原备注与中间体选项，服务端关闭强制重算以保护 checkpoint。</p>}
      </details>
    </>
  );
}
