import { useState } from 'react';
import { FileText, RefreshCw } from 'lucide-react';
import type { Project } from '../../api/types';
import { useJobs } from './useJobs';
import { JobActions } from './JobActions';
import { dateText } from '../../model/presentation';
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
    <section className="management-page jobs-page" aria-labelledby="jobs-heading">
      <header className="page-header">
        <h1 id="jobs-heading">任务记录</h1>
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
            <RefreshCw size={16} aria-hidden="true" />
          </button>
        </div>
      </header>
      {resource.error ? (
        <ErrorNotice error={resource.error} onRetry={resource.reload} />
      ) : resource.loading && !resource.data ? (
        <Loading label="正在读取任务记录…" />
      ) : !resource.data?.items.length ? (
        <Empty title="尚无提取任务" description="上传 PDF 开始，或从最近文件打开已有结果。" />
      ) : (
        <ul className="job-history" aria-label="提取任务记录">
          {resource.data.items.map((job) => {
            const project = projects.find((item) => item.id === job.project_id) ?? null;
            return (
              <li className="job-card" key={job.id}>
                <header>
                  <div className="job-file">
                    <span className="job-file-icon" aria-hidden="true">
                      <FileText size={19} />
                    </span>
                    <button
                      type="button"
                      className="link-button"
                      onClick={() => onOpen(job.project_id)}
                    >
                      {project?.title ?? '打开关联文件'}
                    </button>
                  </div>
                  <time className="job-timestamp" dateTime={job.created_at} title="创建时间">
                    {dateText(job.created_at)}
                  </time>
                </header>
                <div className="job-card-body">
                  <JobActions
                    project={project}
                    job={job}
                    ready={ready}
                    onChange={resource.reload}
                  />
                </div>
              </li>
            );
          })}
        </ul>
      )}
    </section>
  );
}
