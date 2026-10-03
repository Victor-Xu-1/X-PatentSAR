import { useCallback, useState } from 'react';
import { FileText, MapPin } from 'lucide-react';
import { api, safeAssetUrl } from '../../api';
import type { Project } from '../../api/types';
import type { PdfTab } from '../../model/route';
import { useResource } from '../../hooks/useResource';
import { Tabs } from '../../components/Tabs';
import { Empty, ErrorNotice, Loading } from '../../components/Feedback';
import { PageControls } from './PageControls';
import { PageCanvas } from './PageCanvas';

const modeLabels = {
  native: '原生 PDF 文本',
  ocr: '原始 PDF · OCR 文本',
  historical: '历史 OCR 文本（非原生文本）',
  unavailable: '此页文本未提供',
};
export function PdfPane({
  project,
  page,
  tab,
  selectedId,
  onPage,
  onTab,
  onSelect,
  onAttach,
}: {
  project: Project | null;
  page: number | null;
  tab: PdfTab;
  selectedId: string | null;
  onPage: (page: number) => void;
  onTab: (tab: PdfTab) => void;
  onSelect: (id: string) => void;
  onAttach: () => void;
}) {
  const [zoom, setZoom] = useState(1);
  const id = project?.id ?? null;
  const canRead = Boolean(
    id &&
    project &&
    page !== null &&
    Number.isSafeInteger(page) &&
    page >= 1 &&
    project.pdf.page_count >= page,
  );
  const load = useCallback(
    (signal: AbortSignal) =>
      page === null
        ? Promise.reject(new Error('结构来源页尚未确定。'))
        : api.page(id ?? '', page, signal),
    [id, page],
  );
  const resource = useResource(canRead ? `${id}:${page}` : null, load);
  const data = resource.data;
  const imageLabel = data
    ? project?.pdf.available && safeAssetUrl(data.image_url)
      ? data.source_mode === 'historical'
        ? '原始 PDF · 历史 OCR 待复核'
        : data.source_mode === 'native'
          ? '原始 PDF · 原生文本'
          : data.source_mode === 'ocr'
            ? '原始 PDF · OCR 文本'
            : '原始 PDF · 文本未提供'
      : '原文未附'
    : project?.pdf.available && page === null
      ? '等待结构来源页'
      : project?.pdf.available
        ? '原始 PDF · 正在读取来源'
        : project
          ? '原文未附'
          : '仅展示真实原始 PDF';
  return (
    <section className="panel pdf-pane" aria-label="专利原始文档查看器">
      <header className="pdf-toolbar">
        <Tabs
          label="专利文档视图"
          value={tab}
          onChange={onTab}
          tabs={[
            { value: 'original', label: '原文视图' },
            { value: 'text', label: '文本视图' },
            { value: 'annotations', label: '结构标注' },
          ]}
        />
        <PageControls
          key={page}
          page={page}
          total={project?.pdf.page_count ?? 0}
          zoom={zoom}
          disabled={!project || !project.pdf.page_count}
          onPage={onPage}
          onZoom={setZoom}
        />
      </header>
      <div
        className="pdf-content"
        role="tabpanel"
        aria-label={
          tab === 'text' ? '页面提取文本' : tab === 'annotations' ? '原文结构标注' : '原始页面 PNG'
        }
        aria-busy={resource.loading}
      >
        {resource.error ? (
          <ErrorNotice error={resource.error} onRetry={resource.reload} />
        ) : resource.loading && !data ? (
          <Loading label="正在读取原始页面…" />
        ) : !project ? (
          <Empty
            title="原始专利文档"
            description="选择已有项目，或上传专利 PDF。原文、提取文本与结构证据将在这里同步展示。"
          />
        ) : page === null && project.pdf.available ? (
          <Empty
            title="等待结构来源页"
            description="结构定位后自动显示首个来源页，也可以先浏览原文。"
            action={
              <button type="button" onClick={() => onPage(1)}>
                浏览原文
              </button>
            }
          />
        ) : !canRead ? (
          <Empty
            title={project.pdf.available ? '页码超出范围' : '尚未提供原始 PDF'}
            description={
              project.pdf.available
                ? '此页超出原始 PDF 页数；可返回第 1 页继续查看。'
                : '尚未附带原始 PDF。已有提取数据保留来源标记；补充对应原文后即可逐页查看，不生成替代页面。'
            }
            action={
              !project.pdf.available ? (
                <button type="button" onClick={onAttach}>
                  补充原始 PDF
                </button>
              ) : (
                <button type="button" onClick={() => onPage(1)}>
                  返回第 1 页
                </button>
              )
            }
          />
        ) : data ? (
          <>
            {tab === 'text' ? (
              <div className="page-text">
                <div className="source-mode">
                  <FileText size={15} />
                  {modeLabels[data.source_mode]}
                </div>
                {data.text ? (
                  <pre>{data.text}</pre>
                ) : (
                  <Empty
                    title="此页暂无提取文本"
                    description="原始图像仍可在原文视图查看，服务端尚未提供文字内容。"
                  />
                )}
              </div>
            ) : (
              <PageCanvas
                page={data}
                zoom={zoom}
                annotations={tab === 'annotations' || selectedId !== null}
                selectedId={selectedId}
                onSelect={onSelect}
              />
            )}
            {tab === 'annotations' && (
              <div className="annotation-list" aria-label="当前页结构标注列表">
                {data.annotations.length ? (
                  data.annotations.map((annotation, index) => (
                    <button
                      type="button"
                      key={`${annotation.compound_id}-${index}`}
                      className={selectedId === annotation.compound_id ? 'active' : ''}
                      onClick={() => onSelect(annotation.compound_id)}
                    >
                      <MapPin size={14} />
                      {annotation.compound_id}
                      <span>
                        {annotation.kind} · {annotation.verified ? '证据已确认' : '未确认'}
                      </span>
                    </button>
                  ))
                ) : (
                  <p className="muted">此页暂无结构标注；不代表文档提取完成。</p>
                )}
              </div>
            )}
          </>
        ) : null}
      </div>
      <footer className="sr-only">
        <FileText size={13} />
        <span>{imageLabel}</span>
        {project?.patent_id && <span>{project.patent_id}</span>}
      </footer>
    </section>
  );
}
