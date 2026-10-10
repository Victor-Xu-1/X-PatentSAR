import { useState } from 'react';
import { sarApi } from '../../api/sarApi';
import type { Region, RegionRequest } from '../../api/sarTypes';
import { readSavedRegion } from './readSavedRegion';
import { useSARMutation } from './useSARMutation';

/** Region-specific receipts delegate dispatch ownership and locking to the shared mutation hook. */
export function useRegionSave({
  datasetId,
  request,
  scope,
  active,
  onSaved,
}: {
  datasetId: string;
  request: RegionRequest | null;
  scope: string;
  active: boolean;
  onSaved: (region: Region) => void;
}) {
  const identity = JSON.stringify([datasetId, request]);
  const mutation = useSARMutation({ scope: JSON.stringify([scope, identity]), active });
  const [saved, setSaved] = useState<{ identity: string; region: Region } | null>(null);
  const [pending, setPending] = useState<{
    identity: string;
    request: RegionRequest;
    phase: 'write' | 'readback';
  } | null>(null);
  const current = saved?.identity === identity ? saved.region : null;
  const canRecover =
    pending?.identity === identity &&
    !current &&
    (mutation.uncertain || mutation.success || pending.phase === 'readback');
  function accept(region: Region) {
    setSaved({ identity, region });
    setPending(null);
    onSaved(region);
  }
  return {
    mutation,
    saved: current,
    canRecover,
    save: () => {
      if (!request) return;
      setPending({ identity, request, phase: 'write' });
      void mutation.run(() => sarApi.saveRegion(datasetId, request), accept);
    },
    recover: () => {
      if (!canRecover || !pending || mutation.busy) return;
      setPending({ ...pending, phase: 'readback' });
      void mutation.run(() => readSavedRegion(datasetId, pending.request), accept);
    },
    clear: () => {
      setSaved(null);
      setPending(null);
      mutation.clearError();
    },
  };
}
