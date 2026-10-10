import { useTranslation } from '../../i18n';
import { useState } from 'react';
import { FileText, RefreshCw } from 'lucide-react';
import type { Project } from '../../api/types';
import type { Resource } from '../../hooks/useResource';
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
  projects: Resource<{ items: Project[] }>;
  ready: boolean;
  onOpen: (id: string) => void;
  onHistoryChanged?: (entry: HistoryEntry) => void;
}) {
  const { t } = useTranslation();
  const [selection, setSelection] = useState<{ id: string; title: string } | null>(null);
  const projectId = selection?.id ?? null;
  const [trashOpen, setTrashOpen] = useState(false);
  const [historyOpen, setHistoryOpen] = useState(false);
  const resource = useJobs(projectId, { detail: false });
  const items = projects.data?.items ?? [];
  const verified = projects.data !== null && !projects.loading && projects.error === null;
  const selectedProject = items.find((project) => project.id === projectId);
  const selectedExists = selectedProject !== undefined;
  // Only a successful current read can prove removal. Loading or failed reads
  // must not silently change the user's task scope to all projects.
  if (verified && selection) {
    if (!selectedProject) setSelection(null);
    else if (selection.title !== selectedProject.title)
      setSelection({ id: selection.id, title: selectedProject.title });
  }
  function changed(entry: HistoryEntry) {
    resource.reload();
    onHistoryChanged?.(entry);
    if (entry.kind === 'project' && entry.deleted_at !== null && entry.id === projectId)
      setSelection(null);
  }
  return (
    <section
      className="management-page jobs-page"
      aria-labelledby="jobs-heading"
      data-dialog-focus-scope
    >
      <header className="page-header">
        <h1 id="jobs-heading">{t('任务记录')}</h1>
        <div className="inline-actions">
          <select
            aria-label={t('筛选任务所属项目')}
            aria-busy={projects.loading}
            disabled={!verified}
            value={projectId ?? ''}
            onChange={(e) => {
              if (!verified) return;
              const value = e.target.value;
              if (!value) setSelection(null);
              else {
                const project = items.find((item) => item.id === value);
                if (project) setSelection({ id: project.id, title: project.title });
              }
            }}
          >
            <option value="">{t('全部项目')}</option>
            {selection && !selectedExists && !verified && (
              <option value={selection.id}>{selection.title}</option>
            )}
            {items.map((project) => (
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
            {t('全部记录')}
          </button>
          <button
            type="button"
            data-dialog-focus-fallback
            onClick={() => setTrashOpen(true)}
            className="history-trash-button"
          >
            {t('回收站')}
          </button>
          <button
            type="button"
            aria-label={t('刷新任务记录')}
            disabled={projects.loading || resource.loading}
            onClick={() => {
              projects.reload();
              resource.reload();
            }}
          >
            <RefreshCw size={16} aria-hidden="true" />
          </button>
        </div>
      </header>
      {projects.error && <ErrorNotice error={projects.error} onRetry={projects.reload} />}
      {resource.error ? (
        <ErrorNotice error={resource.error} onRetry={resource.reload} />
      ) : resource.loading && !resource.data ? (
        <Loading label={t('正在读取任务记录…')} />
      ) : !resource.data?.items.length ? (
        <Empty
          title={t('尚无提取任务')}
          description={t('上传 PDF 开始，或从最近文件打开已有结果。')}
        />
      ) : (
        <ul className="job-history" aria-label={t('提取任务记录')}>
          {resource.data.items.map((job) => {
            const project = verified
              ? (items.find((item) => item.id === job.project_id) ?? null)
              : null;
            const title =
              project?.title ??
              (selection?.id === job.project_id ? selection.title : t('打开关联文件'));
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
                      {title}
                    </button>
                  </div>
                  <time className="job-timestamp" dateTime={job.created_at} title={t('创建时间')}>
                    {dateText(job.created_at)}
                  </time>
                  <HistoryActions
                    target={{
                      kind: 'job',
                      id: job.id,
                      title: t('{title} · {date}', {
                        title,
                        date: dateText(job.created_at),
                      }),
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
                    onOpenWorkspace={onOpen}
                  />
                </div>
              </li>
            );
          })}
        </ul>
      )}
      {trashOpen && (
        <HistoryDialog
          title={t('回收站')}
          initialKind="job"
          deleted
          filters
          onClose={() => setTrashOpen(false)}
          onChanged={changed}
        />
      )}
      {historyOpen && (
        <HistoryDialog
          title={t('全部任务记录')}
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
