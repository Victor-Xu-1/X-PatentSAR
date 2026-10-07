import { useId } from 'react';
import { ChevronRight, FileText } from 'lucide-react';
import type { Project } from '../../api/types';
import type { Resource } from '../../hooks/useResource';
import { dateText, acceptanceLabels } from '../../model/presentation';
import { Empty, ErrorNotice, Loading } from '../../components/Feedback';
export function ProjectsPage({
  resource,
  onOpen,
  onUpload,
}: {
  resource: Resource<{ items: Project[] }>;
  onOpen: (id: string) => void;
  onUpload: () => void;
}) {
  const metadataId = useId();
  const items = [...(resource.data?.items ?? [])].sort((a, b) =>
    b.updated_at.localeCompare(a.updated_at),
  );
  return (
    <section className="management-page recent-files-page" aria-labelledby="recent-files-heading">
      <header className="page-header">
        <h1 id="recent-files-heading">最近文件</h1>
      </header>
      {resource.error ? (
        <ErrorNotice error={resource.error} onRetry={resource.reload} />
      ) : resource.loading && !resource.data ? (
        <Loading label="正在读取最近文件…" />
      ) : !items.length ? (
        <Empty
          title="还没有文件"
          description="上传一份 PDF 开始。"
          action={
            <button type="button" onClick={onUpload}>
              上传 PDF
            </button>
          }
        />
      ) : (
        <ul className="recent-files" aria-label="最近专利文件">
          {items.map((project, index) => (
            <li key={project.id}>
              <button
                type="button"
                className="recent-file"
                aria-label={`打开 ${project.title}`}
                aria-describedby={`${metadataId}-${index}-source ${metadataId}-${index}-acceptance ${metadataId}-${index}-updated`}
                onClick={() => onOpen(project.id)}
              >
                <span className="recent-file-icon" aria-hidden="true">
                  <FileText size={22} />
                </span>
                <span className="recent-file-name">
                  <strong title={project.title}>{project.title}</strong>
                  <small id={`${metadataId}-${index}-source`}>
                    {project.pdf.available ? `${project.pdf.page_count} 页` : '原文未提供'}
                  </small>
                </span>
                <span
                  id={`${metadataId}-${index}-acceptance`}
                  className={`badge recent-file-acceptance ${project.acceptance.state}`}
                >
                  {acceptanceLabels[project.acceptance.state]}
                </span>
                <time id={`${metadataId}-${index}-updated`} dateTime={project.updated_at}>
                  {dateText(project.updated_at)}
                </time>
                <ChevronRight size={16} className="recent-file-chevron" aria-hidden="true" />
              </button>
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}
