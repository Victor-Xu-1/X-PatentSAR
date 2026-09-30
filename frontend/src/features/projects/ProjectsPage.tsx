import { FileText, FolderOpen, Upload } from 'lucide-react';
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
  return (
    <section className="panel management-page">
      <header className="page-header">
        <div>
          <span className="eyebrow">PATENT WORKSPACE</span>
          <h1>专利项目</h1>
          <p className="muted">从原始文档到可溯源的结构–活性证据</p>
        </div>
        <button type="button" className="primary" onClick={onUpload}>
          <Upload size={16} />
          新建项目
        </button>
      </header>
      {resource.error ? (
        <ErrorNotice error={resource.error} onRetry={resource.reload} />
      ) : resource.loading && !resource.data ? (
        <Loading />
      ) : !resource.data?.items.length ? (
        <Empty
          title="还没有专利项目"
          description="上传原始 PDF 后开始提取。历史结果可由运营人员通过既有 CLI 导入，不在网页中接受任意服务器路径。"
          action={
            <button type="button" onClick={onUpload}>
              上传第一份专利 PDF
            </button>
          }
        />
      ) : (
        <div className="project-grid">
          {resource.data.items.map((project) => (
            <article className="project-card" key={project.id}>
              <div className="project-card-top">
                <span className="project-icon">
                  <FileText size={23} />
                </span>
                <span className={`badge ${project.acceptance.state}`}>
                  {acceptanceLabels[project.acceptance.state]}
                </span>
              </div>
              <h2>{project.title}</h2>
              <p>{project.patent_id ?? '专利标识未提供'}</p>
              <dl>
                <dt>结构 / 活性</dt>
                <dd>
                  {project.summary.structures} / {project.summary.activity_rows}
                </dd>
                <dt>原始 PDF</dt>
                <dd>{project.pdf.available ? `${project.pdf.page_count} 页` : '未提供'}</dd>
                <dt>来源</dt>
                <dd>{project.is_historical ? '历史运行导入' : '原始 PDF 上传'}</dd>
                <dt>更新时间</dt>
                <dd>{dateText(project.updated_at)}</dd>
              </dl>
              <button type="button" onClick={() => onOpen(project.id)}>
                <FolderOpen size={15} />
                打开工作台
              </button>
            </article>
          ))}
        </div>
      )}
    </section>
  );
}
