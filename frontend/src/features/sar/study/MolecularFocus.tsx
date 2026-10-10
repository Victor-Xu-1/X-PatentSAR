import { useLayoutEffect, useRef, useState } from 'react';
import { Minus, Plus } from 'lucide-react';
import { Dialog } from '../../../components/Dialog';
import { useTranslation } from '../../../i18n';

/** Read-only magnification of the already validated drawing, never a second renderer. */
export function MolecularFocus({
  url,
  label,
  onClose,
}: {
  url: string;
  label: string;
  onClose: () => void;
}) {
  const { t } = useTranslation();
  const [zoom, setZoom] = useState(1),
    [failed, setFailed] = useState(false);
  const viewport = useRef<HTMLElement>(null),
    previousZoom = useRef(1);
  useLayoutEffect(() => {
    const pane = viewport.current;
    if (pane) {
      // Only magnified overflow is keyboard-interactive. Explicit current-state
      // focusability also lets the shared modal boundary include native scrolling.
      pane.tabIndex = zoom > 1 ? 0 : -1;
      const ratio = zoom / previousZoom.current;
      pane.scrollLeft =
        zoom === 1 ? 0 : (pane.scrollLeft + pane.clientWidth / 2) * ratio - pane.clientWidth / 2;
      pane.scrollTop =
        zoom === 1 ? 0 : (pane.scrollTop + pane.clientHeight / 2) * ratio - pane.clientHeight / 2;
    }
    previousZoom.current = zoom;
  }, [zoom]);
  return (
    <Dialog
      title={t('结构预览 · {identifier}', { identifier: label })}
      onClose={onClose}
      wide
      className="sar-molecule-focus"
    >
      <div className="dialog-body sar-molecule-focus-body">
        <div className="sar-molecule-focus-toolbar">
          <span>{t('结构重绘（非原图）')}</span>
          <div>
            <button
              type="button"
              className="icon-button"
              aria-label={t('缩小结构')}
              disabled={failed || zoom <= 1}
              onClick={() => setZoom((value) => Math.max(1, value - 0.25))}
            >
              <Minus size={16} />
            </button>
            <output aria-label={t('相对适应窗口的放大比例')}>{Math.round(zoom * 100)}%</output>
            <button
              type="button"
              className="icon-button"
              aria-label={t('放大结构')}
              disabled={failed || zoom >= 4}
              onClick={() => setZoom((value) => Math.min(4, value + 0.25))}
            >
              <Plus size={16} />
            </button>
            <button type="button" data-initial-focus disabled={failed} onClick={() => setZoom(1)}>
              {t('适应窗口')}
            </button>
          </div>
        </div>
        {failed ? (
          <p role="alert">{t('RDKit 结构图加载失败。')}</p>
        ) : (
          <section
            ref={viewport}
            className="sar-molecule-focus-viewport"
            aria-label={t('结构查看区域')}
          >
            <div
              className="sar-molecule-focus-canvas"
              style={{ width: `${zoom * 100}%`, height: `${zoom * 100}%` }}
            >
              <img src={url} alt={label} draggable={false} onError={() => setFailed(true)} />
            </div>
          </section>
        )}
      </div>
    </Dialog>
  );
}
