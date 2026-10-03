import { useState } from 'react';
import { RefreshCw } from 'lucide-react';
import type { Project } from '../../api/types';
import { useJobs } from './useJobs';
import { StageStrip } from './StageStrip';
import { JobActions } from './JobActions';
import { dateText, jobStatusLabels } from '../../model/presentation';
import { Empty, ErrorNotice, Loading } from '../../components/Feedback';
export function JobsPage({
  projects,
  ready,
  onOpen,
}: {
  projects: Project[];
  ready: boolean;
  onOpen: (id: string) => void;
}) {
  const [projectId, setProjectId] = useState<string | null>(null);
  const resource = useJobs(projectId);
  return (
    <section className="panel management-page">
      <header className="page-header">
        <div>
          <h1>任务记录</h1>
        </div>
        <div className="inline-actions">
          <select
            aria-label="筛选任务所属项目"
            value={projectId ?? ''}
            onChange={(e) => setProjectId(e.target.value || null)}
          >
            <option value="">全部项目</option>
            {projects.map((project) => (
              <option key={project.id} value={project.id}>
                {project.title}
              </option>
            ))}
          </select>
          <button type="button" aria-label="刷新任务记录" onClick={resource.reload}>
            <RefreshCw size={16} />
          </button>
        </div>
      </header>
      {resource.error ? (
        <ErrorNotice error={resource.error} onRetry={resource.reload} />
      ) : resource.loading && !resource.data ? (
        <Loading />
      ) : !resource.data?.items.length ? (
        <Empty
          title="尚无提取任务"
          description="打开有原始 PDF 的项目，在工作台运行提取。取消与恢复仅作用于所选项目的任务。"
        />
      ) : (
        <div className="job-history">
          {resource.data.items.map((job) => {
            const project = projects.find((item) => item.id === job.project_id) ?? null;
            return (
              <article className="job-card" key={job.id}>
                <header>
                  <div>
                    <button
                      type="button"
                      className="link-button"
                      onClick={() => onOpen(job.project_id)}
                    >
                      {project?.title ?? job.project_id}
                    </button>
                    <span className={`badge job-${job.status}`}>{jobStatusLabels[job.status]}</span>
                  </div>
                  <small title={job.id}>任务 {job.id}</small>
                </header>
                <StageStrip job={job} compact />
                <dl className="job-dates">
                  <dt>创建</dt>
                  <dd>{dateText(job.created_at)}</dd>
                  <dt>开始</dt>
                  <dd>{dateText(job.started_at)}</dd>
                  <dt>结束</dt>
                  <dd>{dateText(job.finished_at)}</dd>
                </dl>
                <JobActions project={project} job={job} ready={ready} onChange={resource.reload} />
              </article>
            );
          })}
        </div>
      )}
    </section>
  );
}
