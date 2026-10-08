import { useTranslation } from '../../i18n';
import { useEffect, useRef, useState } from 'react';
import { safeAssetUrl } from '../../api';
import type { ActivityFocusSelection, PageData } from '../../api/types';
import { Empty } from '../../components/Feedback';
import { ActivityFocusMarks, pageBoxStyle } from './ActivityFocusMarks';
import { preferredScrollBehavior } from '../../model/motion';

export function PageCanvas({
  page,
  zoom,
  annotations,
  selectedId,
  onSelect,
  activityFocus,
}: {
  page: PageData;
  zoom: number;
  annotations: boolean;
  selectedId: string | null;
  onSelect: (id: string) => void;
  activityFocus?: ActivityFocusSelection | undefined;
}) {
  const { t } = useTranslation();
  const ref = useRef<HTMLDivElement>(null);
  const [failed, setFailed] = useState<string | null>(null);
  const [loaded, setLoaded] = useState<string | null>(null);
  const original = safeAssetUrl(page.image_url);
  const width = page.width ?? 0;
  const height = page.height ?? 0;
  const url = original ? `${original.split('?')[0]}?scale=${Math.max(1, zoom)}` : null;
  const focus =
    activityFocus &&
    page.activity_focus?.compound_id === activityFocus.compoundId &&
    page.activity_focus.activity_key === activityFocus.key
      ? page.activity_focus
      : null;
  useEffect(() => {
    if (loaded !== url) return;
    const behavior = preferredScrollBehavior();
    if (focus?.status === 'located') {
      ref.current
        ?.querySelector<HTMLElement>('[data-activity-focus]')
        ?.scrollIntoView({ block: 'center', inline: 'nearest', behavior });
    } else if (!activityFocus && selectedId) {
      Array.from(ref.current?.querySelectorAll<HTMLElement>('[data-annotation]') ?? [])
        .find((element) => element.dataset.annotation === selectedId)
        ?.scrollIntoView({ block: 'center', inline: 'nearest', behavior });
    }
  }, [selectedId, loaded, url, activityFocus, focus]);
  if (!url)
    return (
      <Empty
        title={t('原始 PDF 页面不可用')}
        description={
          page.source_mode === 'historical'
            ? t('此页来自历史导入。历史文本可用于复核，但不是原始页面图像。')
            : t('服务端未提供原始 PDF 图像，不会用合成页面替代来源。')
        }
      />
    );
  if (failed === url)
    return (
      <Empty
        title={t('页面图像加载失败')}
        description={t('原始 PNG 未能加载，请检查会话与文档服务。')}
        action={
          <button type="button" onClick={() => setFailed(null)}>
            {t('重新加载页面图像')}
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
          alt={t('原始专利 PDF 第 {page} 页', { page: page.page })}
          onLoad={() => setLoaded(url)}
          onError={() => {
            setLoaded(null);
            setFailed(url);
          }}
        />
        {loaded !== url && <output className="page-loading">{t('正在加载原始 PNG…')}</output>}
        {loaded === url && width > 0 && height > 0 && focus?.status === 'located' && (
          <ActivityFocusMarks focus={focus} width={width} height={height} />
        )}
        {annotations &&
          loaded === url &&
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
                aria-label={t('定位化合物 {compound}，{evidence}', {
                  compound: annotation.compound_id,
                  evidence: t(annotation.verified ? '证据已确认' : '证据未确认'),
                })}
                style={pageBoxStyle([x1, y1, x2, y2], width, height)}
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
