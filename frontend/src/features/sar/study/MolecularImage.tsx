import { useState, type ReactNode } from 'react';
import { Expand } from 'lucide-react';
import { useTranslation } from '../../../i18n';
import type { safeDrawing } from '../safeDrawing';
import { MolecularFocus } from './MolecularFocus';

/** One passive image/load/focus boundary for validated study and reference views. */
export function MolecularImage({
  image,
  identity,
  label,
  authorized,
  inspectable = false,
  inspectionTrigger = 'control',
  children,
}: {
  image: ReturnType<typeof safeDrawing> | null;
  identity: string;
  label: string;
  authorized: boolean;
  inspectable?: boolean;
  inspectionTrigger?: 'control' | 'image';
  children?: ReactNode;
}) {
  const { t } = useTranslation();
  const [failed, setFailed] = useState<string | null>(null),
    [loaded, setLoaded] = useState<string | null>(null),
    [expanded, setExpanded] = useState<{ identity: string; url: string } | null>(null);
  const imageReady = Boolean(image && loaded === image.url && failed !== image.url);
  const ready = inspectable && authorized && imageReady;
  // Returning to a view must not reopen a modal from a stale owner or source.
  if (expanded && (!ready || expanded.identity !== identity)) setExpanded(null);
  const drawing = image && failed !== image.url && (
    <img
      src={image.url}
      alt={label}
      style={{ aspectRatio: image.aspectRatio }}
      onLoad={inspectable || children !== undefined ? () => setLoaded(image.url) : undefined}
      onError={() => setFailed(image.url)}
    />
  );
  function expand() {
    if (ready && image) setExpanded({ identity, url: image.url });
  }
  return (
    <>
      {drawing &&
        (inspectable && inspectionTrigger === 'image' ? (
          <button
            type="button"
            className="sar-image-focus-trigger"
            aria-label={t('放大结构 {identifier}', { identifier: label })}
            disabled={!ready}
            onClick={expand}
          >
            {drawing}
          </button>
        ) : (
          drawing
        ))}
      {imageReady && children}
      {ready && image && inspectionTrigger === 'control' && (
        <button
          type="button"
          className="icon-button sar-image-focus-action"
          aria-label={t('放大结构 {identifier}', { identifier: label })}
          onClick={expand}
        >
          <Expand size={17} />
        </button>
      )}
      {ready && expanded?.identity === identity && expanded.url === image?.url && (
        <MolecularFocus
          key={identity}
          url={expanded.url}
          label={label}
          onClose={() => setExpanded(null)}
        />
      )}
      {image && failed === image.url && <p role="alert">{t('RDKit 结构图加载失败。')}</p>}
    </>
  );
}
