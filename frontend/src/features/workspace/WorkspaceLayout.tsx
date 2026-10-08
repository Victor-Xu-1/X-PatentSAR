import { useTranslation } from '../../i18n';
import { useEffect, useRef, useState } from 'react';
import type { CSSProperties, ReactNode } from 'react';
import { Maximize2, Minimize2, PanelLeftClose, PanelLeftOpen } from 'lucide-react';
import { defaultLayout, normalizeLayout } from '../../model/layout';
import type { LayoutState } from '../../model/layout';
import { ResizeHandle } from '../../components/ResizeHandle';
import { containTab } from '../../components/focus';

export function WorkspaceLayout({
  layout: input,
  onChange,
  source,
  results,
}: {
  layout: LayoutState;
  onChange: (layout: LayoutState) => void;
  source: ReactNode;
  results: ReactNode;
}) {
  const { t } = useTranslation();
  const layout = normalizeLayout(input);
  const split = useRef<HTMLDivElement>(null);
  const root = useRef<HTMLDivElement>(null);
  const fullButton = useRef<HTMLButtonElement>(null);
  const [preview, setPreview] = useState<number | null>(null);
  useEffect(() => {
    if (!layout.fullscreen) return;
    const previous = document.body.style.overflow;
    document.body.style.overflow = 'hidden';
    fullButton.current?.focus();
    return () => {
      document.body.style.overflow = previous;
    };
  }, [layout.fullscreen]);
  useEffect(() => {
    if (!layout.fullscreen) return;
    const handleKey = (e: KeyboardEvent) => {
      if (!layout.fullscreen || document.querySelector('dialog[open]')) return;
      if (e.key === 'Escape') {
        e.preventDefault();
        onChange({ ...layout, fullscreen: false });
        fullButton.current?.focus();
      }
      containTab(e, root.current);
    };
    document.addEventListener('keydown', handleKey);
    return () => document.removeEventListener('keydown', handleKey);
  }, [layout, onChange]);
  return (
    <div
      ref={root}
      className={`workspace-layout${layout.fullscreen ? ' is-fullscreen' : ''}${layout.pdfVisible ? '' : ' source-collapsed'}`}
    >
      <div className="layout-toolbar" aria-label={t('工作区布局')}>
        <button
          type="button"
          onClick={() => onChange({ ...layout, pdfVisible: !layout.pdfVisible })}
          aria-label={layout.pdfVisible ? t('收起原文，结果全宽') : t('展开原文')}
          aria-expanded={layout.pdfVisible}
          aria-controls="workspace-source"
        >
          {layout.pdfVisible ? <PanelLeftClose size={14} /> : <PanelLeftOpen size={14} />}
          {layout.pdfVisible ? t('收起原文') : t('展开原文')}
        </button>
        <button
          ref={fullButton}
          type="button"
          onClick={() => onChange({ ...layout, fullscreen: !layout.fullscreen })}
          aria-label={layout.fullscreen ? t('退出全屏工作区') : t('全屏工作区')}
          aria-pressed={layout.fullscreen}
        >
          {layout.fullscreen ? <Minimize2 size={14} /> : <Maximize2 size={14} />}
          {layout.fullscreen ? t('退出全屏') : t('全屏')}
        </button>
      </div>
      <div
        className="workspace-split"
        ref={split}
        style={
          {
            '--pdf-width': `${preview ?? layout.pdfWidth}fr`,
            '--result-width': `${100 - (preview ?? layout.pdfWidth)}fr`,
          } as CSSProperties
        }
      >
        {layout.pdfVisible && (
          <>
            <div id="workspace-source" className="workspace-source">
              {source}
            </div>
            <ResizeHandle
              className="workspace-divider"
              label={t('调整原文与结果宽度')}
              controls="workspace-source workspace-results"
              value={preview ?? layout.pdfWidth}
              min={20}
              max={55}
              keyStep={2}
              resetValue={defaultLayout.pdfWidth}
              valueText={t('原文 {source}%，结果 {results}%', {
                source: preview ?? layout.pdfWidth,
                results: 100 - (preview ?? layout.pdfWidth),
              })}
              fromPointer={(delta, initial) => {
                const width = split.current?.getBoundingClientRect().width ?? 0;
                return width > 10 ? initial + (delta / (width - 10)) * 100 : NaN;
              }}
              onPreview={setPreview}
              onCommit={(pdfWidth) => onChange({ ...layout, pdfWidth })}
            />
          </>
        )}
        <div id="workspace-results" className="workspace-results">
          {results}
        </div>
      </div>
    </div>
  );
}
