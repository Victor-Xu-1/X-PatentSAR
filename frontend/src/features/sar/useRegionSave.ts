import { useState } from 'react';
import { sarApi } from '../../api/sarApi';
import type { Region, RegionRequest } from '../../api/sarTypes';
import { readSavedRegion, RegionReadbackError } from './readSavedRegion';
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
    phase: 'write' | 'readback' | 'retry';
  } | null>(null);
  const current = saved?.identity === identity ? saved.region : null;
  const canRecover =
    pending?.identity === identity &&
    !current &&
    (mutation.uncertain || mutation.success || pending.phase === 'readback');
  const canResubmit =
    pending?.identity === identity &&
    !current &&
    ((mutation.error instanceof RegionReadbackError && mutation.error.missingSavedSelection) ||
      (pending.phase === 'retry' && mutation.busy));
  function accept(region: Region) {
    setSaved({ identity, region });
    setPending(null);
    onSaved(region);
  }
  function write(payload: RegionRequest, phase: 'write' | 'retry') {
    setPending({ identity, request: payload, phase });
    void mutation.run(() => sarApi.saveRegion(datasetId, payload), accept);
  }
  return {
    mutation,
    saved: current,
    canRecover,
    canResubmit,
    save: () => {
      if (!request) return;
      write(request, 'write');
    },
    recover: () => {
      if (!canRecover || !pending || mutation.busy) return;
      setPending({ ...pending, phase: 'readback' });
      void mutation.run(() => readSavedRegion(datasetId, pending.request), accept);
    },
    resubmit: () => {
      if (!active || !canResubmit || !pending || mutation.busy) return;
      // Same captured graph/revision/atoms/name/purpose, never a new draft.
      // The existing server's content identity makes even a delayed first
      // commit safe: the repeated request returns its original receipt.
      write(pending.request, 'retry');
    },
    clear: () => {
      setSaved(null);
      setPending(null);
      mutation.clearError();
    },
  };
}
