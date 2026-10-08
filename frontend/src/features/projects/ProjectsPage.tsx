import { useId, useState } from 'react';
import { ChevronRight, FileText } from 'lucide-react';
import type { Project } from '../../api/types';
import type { Resource } from '../../hooks/useResource';
import { dateText, acceptanceLabels } from '../../model/presentation';
import { Empty, ErrorNotice, Loading } from '../../components/Feedback';
import type { HistoryEntry } from '../../api/historyTypes';
import { HistoryActions } from '../history/HistoryActions';
import { HistoryDialog } from '../history/HistoryDialog';
import { useTranslation } from '../../i18n';
export function ProjectsPage({
  resource,
  onOpen,
  onUpload,
  onHistoryChanged,
}: {
  resource: Resource<{ items: Project[] }>;
  onOpen: (id: string) => void;
  onUpload: () => void;
  onHistoryChanged?: (entry: HistoryEntry) => void;
}) {
  const { t } = useTranslation();
  const metadataId = useId();
  const [trashOpen, setTrashOpen] = useState(false);
  const [files, setFiles] = useState<Project | null>(null);
  function changed(entry: HistoryEntry) {
    resource.reload();
    onHistoryChanged?.(entry);
    if (entry.kind === 'project' && entry.deleted_at !== null && files?.id === entry.id)
      setFiles(null);
  }
  const items = [...(resource.data?.items ?? [])].sort((a, b) =>
    b.updated_at.localeCompare(a.updated_at),
  );
  return (
    <section
      className="management-page recent-files-page"
      aria-labelledby="recent-files-heading"
      data-dialog-focus-scope
    >
      <header className="page-header">
        <h1 id="recent-files-heading">{t('最近文件')}</h1>
        <button type="button" data-dialog-focus-fallback onClick={() => setTrashOpen(true)}>
          {t('回收站')}
        </button>
      </header>
      {resource.error ? (
        <ErrorNotice error={resource.error} onRetry={resource.reload} />
      ) : resource.loading && !resource.data ? (
        <Loading label={t('正在读取最近文件…')} />
      ) : !items.length ? (
        <Empty
          title={t('还没有文件')}
          description={t('上传一份 PDF 开始。')}
          action={
            <button type="button" onClick={onUpload}>
              {t('上传 PDF')}
            </button>
          }
        />
      ) : (
        <ul className="recent-files" aria-label={t('最近专利文件')}>
          {items.map((project, index) => (
            <li key={project.id} className="recent-file-row">
              <button
                type="button"
                className="recent-file"
                aria-label={t('打开 {title}', { title: project.title })}
                aria-describedby={`${metadataId}-${index}-source ${metadataId}-${index}-acceptance ${metadataId}-${index}-updated`}
                onClick={() => onOpen(project.id)}
              >
                <span className="recent-file-icon" aria-hidden="true">
                  <FileText size={22} />
                </span>
                <span className="recent-file-name">
                  <strong title={project.title}>{project.title}</strong>
                  <small id={`${metadataId}-${index}-source`}>
                    {project.pdf.available
                      ? t('{pages} 页', { pages: project.pdf.page_count })
                      : t('原文未提供')}
                  </small>
                </span>
                <span
                  id={`${metadataId}-${index}-acceptance`}
                  className={`badge recent-file-acceptance ${project.acceptance.state}`}
                >
                  {t(acceptanceLabels[project.acceptance.state])}
                </span>
                <time id={`${metadataId}-${index}-updated`} dateTime={project.updated_at}>
                  {dateText(project.updated_at)}
                </time>
                <ChevronRight size={16} className="recent-file-chevron" aria-hidden="true" />
              </button>
              <div className="recent-file-actions">
                <button
                  type="button"
                  aria-label={t('已生成文件 {title}', { title: project.title })}
                  onClick={() => setFiles(project)}
                >
                  {t('已生成文件')}
                </button>
                <HistoryActions
                  target={{ kind: 'project', id: project.id, title: project.title }}
                  iconOnly
                  onChanged={changed}
                />
              </div>
            </li>
          ))}
        </ul>
      )}
      {files && (
        <HistoryDialog
          title={t('已生成文件 · {title}', { title: files.title })}
          initialKind="export"
          projectId={files.id}
          onClose={() => setFiles(null)}
          onChanged={changed}
          onTrash={() => {
            setFiles(null);
            setTrashOpen(true);
          }}
        />
      )}
      {trashOpen && (
        <HistoryDialog
          title={t('回收站')}
          initialKind="project"
          deleted
          filters
          onClose={() => setTrashOpen(false)}
          onChanged={changed}
        />
      )}
    </section>
  );
}
