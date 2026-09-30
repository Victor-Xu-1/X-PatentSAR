import { useEffect, useRef, useState } from 'react';
import { safeAssetUrl } from '../../api';
import type { PageData } from '../../api/types';
import { Empty } from '../../components/Feedback';

export function PageCanvas({
  page,
  zoom,
  annotations,
  selectedId,
  onSelect,
}: {
  page: PageData;
  zoom: number;
  annotations: boolean;
  selectedId: string | null;
  onSelect: (id: string) => void;
}) {
  const ref = useRef<HTMLDivElement>(null);
  const [failed, setFailed] = useState<string | null>(null);
  const [loaded, setLoaded] = useState<string | null>(null);
  const original = safeAssetUrl(page.image_url);
  const width = page.width ?? 0;
  const height = page.height ?? 0;
  const url = original ? `${original.split('?')[0]}?scale=${Math.max(1, zoom)}` : null;
  useEffect(() => {
    if (selectedId && loaded === url) {
      Array.from(ref.current?.querySelectorAll<HTMLElement>('[data-annotation]') ?? [])
        .find((element) => element.dataset.annotation === selectedId)
        ?.scrollIntoView({ block: 'center', inline: 'nearest', behavior: 'smooth' });
    }
  }, [selectedId, loaded, url]);
  if (!url)
    return (
      <Empty
        title="原始 PDF 页面不可用"
        description={
          page.source_mode === 'historical'
            ? '此页来自历史导入。历史文本可用于复核，但不是原始页面图像。'
            : '服务端未提供原始 PDF 图像，不会用合成页面替代来源。'
        }
      />
    );
  if (failed === url)
    return (
      <Empty
        title="页面图像加载失败"
        description="原始 PNG 未能加载，请检查会话与文档服务。"
        action={
          <button type="button" onClick={() => setFailed(null)}>
            重新加载页面图像
          </button>
        }
      />
    );
  return (
    <div className="pdf-scroll">
      <div
        className="page-canvas"
        ref={ref}
        style={{
          width: `${zoom * 100}%`,
          aspectRatio: width > 0 && height > 0 ? `${width} / ${height}` : undefined,
        }}
      >
        <img
          src={url}
          alt={`原始专利 PDF 第 ${page.page} 页`}
          onLoad={() => setLoaded(url)}
          onError={() => setFailed(url)}
        />
        {loaded !== url && <output className="page-loading">正在加载原始 PNG…</output>}
        {annotations &&
          width > 0 &&
          height > 0 &&
          page.annotations.map((annotation, index) => {
            const [x1, y1, x2, y2] = annotation.bbox;
            if (x2 > width || y2 > height) return null;
            return (
              <button
                type="button"
                className={`annotation-box${annotation.compound_id === selectedId ? ' selected' : ''}${annotation.verified ? ' verified' : ''}`}
                data-annotation={annotation.compound_id}
                key={`${annotation.compound_id}-${index}`}
                aria-label={`定位化合物 ${annotation.compound_id}，${annotation.verified ? '证据已确认' : '证据未确认'}`}
                style={{
                  left: `${(100 * x1) / width}%`,
                  top: `${(100 * y1) / height}%`,
                  width: `${(100 * (x2 - x1)) / width}%`,
                  height: `${(100 * (y2 - y1)) / height}%`,
                }}
                onClick={() => onSelect(annotation.compound_id)}
              >
                <span>{annotation.compound_id}</span>
              </button>
            );
          })}
      </div>
    </div>
  );
}
