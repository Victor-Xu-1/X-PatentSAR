import { useCallback, useMemo, useState } from 'react';
import { sarStudyApi } from '../../../api/sarStudyApi';
import type { StudyDrawingKind } from '../../../api/sarStudyTypes';
import { Loading } from '../../../components/Feedback';
import { useTranslation } from '../../../i18n';
import { SARFailure } from '../SARFailure';
import { safeDrawing } from '../safeDrawing';
import { useSARResource } from '../useSARResource';
export function StudyImage({
  jobId,
  kind,
  identifier,
  regionId = '',
  atomRegionId = '',
  label,
  active,
}: {
  jobId: string;
  kind: StudyDrawingKind;
  identifier: string;
  regionId?: string;
  atomRegionId?: string;
  label: string;
  active: boolean;
}) {
  const { t } = useTranslation(),
    [failed, setFailed] = useState<string | null>(null);
  const load = useCallback(
    (signal: AbortSignal) =>
      sarStudyApi.drawing(jobId, kind, identifier, signal, regionId || atomRegionId),
    [jobId, kind, identifier, regionId, atomRegionId],
  );
  const resource = useSARResource(
    JSON.stringify(['sar:study-drawing', jobId, kind, identifier, regionId, atomRegionId]),
    active,
    load,
  );
  const image = useMemo(() => {
    try {
      return { value: resource.data ? safeDrawing(resource.data.svg) : null, error: null };
    } catch (error) {
      return { value: null, error: error as Error };
    }
  }, [resource.data]);
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
          onError={() => setFailed(image.value!.url)}
        />
      )}
      {image.value && failed === image.value.url && (
        <p role="alert">{t('RDKit 结构图加载失败。')}</p>
      )}
    </figure>
  );
}
