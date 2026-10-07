import { useState } from 'react';
import { FileText, RefreshCw } from 'lucide-react';
import type { Project } from '../../api/types';
import { useJobs } from './useJobs';
import { JobActions } from './JobActions';
import { dateText } from '../../model/presentation';
import { Empty, ErrorNotice, Loading } from '../../components/Feedback';
import type { HistoryEntry } from '../../api/historyTypes';
import { HistoryActions } from '../history/HistoryActions';
import { HistoryDialog } from '../history/HistoryDialog';
export function JobsPage({
  projects,
  ready,
  onOpen,
  onHistoryChanged,
}: {
  projects: Project[];
  ready: boolean;
  onOpen: (id: string) => void;
  onHistoryChanged?: (entry: HistoryEntry) => void;
}) {
  const [projectId, setProjectId] = useState<string | null>(null);
  const [trashOpen, setTrashOpen] = useState(false);
  const [historyOpen, setHistoryOpen] = useState(false);
  const resource = useJobs(projectId);
  if (projectId && !projects.some((project) => project.id === projectId)) setProjectId(null);
  function changed(entry: HistoryEntry) {
    resource.reload();
    onHistoryChanged?.(entry);
    if (entry.kind === 'project' && entry.deleted_at !== null && entry.id === projectId)
      setProjectId(null);
  }
  return (
    <section
      className="management-page jobs-page"
      aria-labelledby="jobs-heading"
      data-dialog-focus-scope
    >
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
          <button
            type="button"
            className="history-trash-button"
            onClick={() => setHistoryOpen(true)}
          >
            全部记录
          </button>
          <button
            type="button"
            data-dialog-focus-fallback
            onClick={() => setTrashOpen(true)}
            className="history-trash-button"
          >
            回收站
          </button>
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
                  <HistoryActions
                    target={{
                      kind: 'job',
                      id: job.id,
                      title: `${project?.title ?? '任务记录'} · ${dateText(job.created_at)}`,
                    }}
                    iconOnly
                    onChanged={changed}
                  />
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
      {trashOpen && (
        <HistoryDialog
          title="回收站"
          initialKind="job"
          deleted
          filters
          onClose={() => setTrashOpen(false)}
          onChanged={changed}
        />
      )}
      {historyOpen && (
        <HistoryDialog
          title="全部任务记录"
          initialKind="job"
          {...(projectId === null ? {} : { projectId })}
          onClose={() => setHistoryOpen(false)}
          onChanged={changed}
          onTrash={() => {
            setHistoryOpen(false);
            setTrashOpen(true);
          }}
        />
      )}
    </section>
  );
}
