import { useCallback } from 'react';
import { sarApi } from '../../api/sarApi';
import type { Dataset, Molecule, SARJob } from '../../api/sarTypes';
import { Loading } from '../../components/Feedback';
import { SARFailure } from './SARFailure';
import { useSARResource } from './useSARResource';
import { SARResults } from './SARResults';
import { StudyResults } from './study/StudyResults';
/** Dispatch from server-owned job kind, including a direct route absent from the list. */
export function SARJobResults({
  known,
  ...props
}: {
  known: SARJob | null;
  dataset: Dataset;
  jobId: string;
  active: boolean;
  disabled: boolean;
  scope: string;
  reference?: Molecule | null;
  onJob: (id: string) => void;
}) {
  const load = useCallback(
    (signal: AbortSignal) => sarApi.job(props.jobId, props.dataset.id, signal),
    [props.jobId, props.dataset.id],
  );
  const resource = useSARResource(
    'sar:job-kind:' + props.jobId,
    props.active && !props.disabled && !known,
    load,
  );
  const kind =
    known?.kind ??
    (known ? 'reference' : (resource.data?.kind ?? (resource.data ? 'reference' : null)));
  if (!kind)
    return (
      <>
        {resource.loading && <Loading />}
        {resource.error && <SARFailure error={resource.error} onRetry={resource.reload} />}
      </>
    );
  return kind === 'study' ? <StudyResults {...props} /> : <SARResults {...props} />;
}
