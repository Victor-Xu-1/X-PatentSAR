import { useCallback, useMemo } from 'react';
import { sarStudyApi } from '../../../api/sarStudyApi';
import { ContractError } from '../../../api/validation';
import type { StudyDrawing, StudyDrawingKind } from '../../../api/sarStudyTypes';
import { Loading } from '../../../components/Feedback';
import { SARFailure } from '../SARFailure';
import { safeDrawing } from '../safeDrawing';
import { useSARResource } from '../useSARResource';
import { MolecularImage } from './MolecularImage';
export function StudyImage({
  jobId,
  kind,
  identifier,
  regionId = '',
  atomRegionId = '',
  label,
  active,
  inspectable = false,
  inspectionTrigger = 'control',
  providedDrawing,
}: {
  jobId: string;
  kind: StudyDrawingKind;
  identifier: string;
  regionId?: string;
  atomRegionId?: string;
  label: string;
  active: boolean;
  inspectable?: boolean;
  inspectionTrigger?: 'control' | 'image';
  /** A receipt-validated paired layout, using the same passive image/focus authority. */
  providedDrawing?: StudyDrawing;
}) {
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
  const resource = useSARResource(identity, active && !providedDrawing, load);
  const source = providedDrawing ?? resource.data;
  const image = useMemo(() => {
    try {
      if (providedDrawing && providedDrawing.id !== identifier)
        throw new ContractError('$.paired_drawing_identity');
      return { value: source ? safeDrawing(source.svg) : null, error: null };
    } catch (error) {
      return { value: null, error: error as Error };
    }
  }, [source, providedDrawing, identifier]);
  return (
    <figure className="sar-study-image">
      {!providedDrawing && resource.loading && <Loading />}
      {!providedDrawing && resource.error && (
        <SARFailure error={resource.error} onRetry={resource.reload} />
      )}
      {image.error && <SARFailure error={image.error} />}
      <MolecularImage
        image={image.value}
        identity={identity}
        label={label}
        authorized={
          active && (providedDrawing ? providedDrawing.id === identifier : resource.validated)
        }
        inspectable={inspectable}
        inspectionTrigger={inspectionTrigger}
      />
    </figure>
  );
}
