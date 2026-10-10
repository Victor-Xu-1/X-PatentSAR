import { useCallback, useMemo, useState } from 'react';
import { Expand } from 'lucide-react';
import { sarStudyApi } from '../../../api/sarStudyApi';
import type { StudyDrawingKind } from '../../../api/sarStudyTypes';
import { Loading } from '../../../components/Feedback';
import { useTranslation } from '../../../i18n';
import { SARFailure } from '../SARFailure';
import { safeDrawing } from '../safeDrawing';
import { useSARResource } from '../useSARResource';
import { MolecularFocus } from './MolecularFocus';
export function StudyImage({
  jobId,
  kind,
  identifier,
  regionId = '',
  atomRegionId = '',
  label,
  active,
  inspectable = false,
}: {
  jobId: string;
  kind: StudyDrawingKind;
  identifier: string;
  regionId?: string;
  atomRegionId?: string;
  label: string;
  active: boolean;
  inspectable?: boolean;
}) {
  const { t } = useTranslation(),
    [failed, setFailed] = useState<string | null>(null),
    [loaded, setLoaded] = useState<string | null>(null),
    [expanded, setExpanded] = useState<{ identity: string; url: string } | null>(null);
  const identity = JSON.stringify([
    'sar:study-drawing',
    jobId,
    kind,
    identifier,
    regionId,
    atomRegionId,
  ]);
  const load = useCallback(
    (signal: AbortSignal) =>
      sarStudyApi.drawing(jobId, kind, identifier, signal, regionId || atomRegionId),
    [jobId, kind, identifier, regionId, atomRegionId],
  );
  const resource = useSARResource(identity, active, load);
  const image = useMemo(() => {
    try {
      return { value: resource.data ? safeDrawing(resource.data.svg) : null, error: null };
    } catch (error) {
      return { value: null, error: error as Error };
    }
  }, [resource.data]);
  const ready = Boolean(
    inspectable &&
    resource.validated &&
    image.value &&
    loaded === image.value.url &&
    failed !== image.value.url,
  );
  // Drop ownership before commit: returning to a view must not reopen an old dialog.
  if (expanded && (!ready || expanded.identity !== identity)) setExpanded(null);
  return (
    <figure className="sar-study-image">
      {resource.loading && <Loading />}
      {resource.error && <SARFailure error={resource.error} onRetry={resource.reload} />}
      {image.error && <SARFailure error={image.error} />}
      {image.value && failed !== image.value.url && (
        <img
          src={image.value.url}
          alt={label}
          style={{ aspectRatio: image.value.aspectRatio }}
          onLoad={inspectable ? () => setLoaded(image.value!.url) : undefined}
          onError={() => setFailed(image.value!.url)}
        />
      )}
      {ready && image.value && (
        <button
          type="button"
          className="icon-button sar-image-focus-action"
          aria-label={t('放大结构 {identifier}', { identifier: label })}
          onClick={() => setExpanded({ identity, url: image.value!.url })}
        >
          <Expand size={17} />
        </button>
      )}
      {ready && expanded?.identity === identity && expanded.url === image.value?.url && (
        <MolecularFocus
          key={identity}
          url={expanded.url}
          label={label}
          onClose={() => setExpanded(null)}
        />
      )}
      {image.value && failed === image.value.url && (
        <p role="alert">{t('RDKit 结构图加载失败。')}</p>
      )}
    </figure>
  );
}
