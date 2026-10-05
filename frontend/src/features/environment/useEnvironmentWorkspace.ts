import { useCallback, useEffect, useRef, useState } from 'react';
import { api } from '../../api';
import { activeEnvironmentOperation } from '../../model/environment';
import { useResource } from '../../hooks/useResource';
import { useEnvironmentMutations } from './useEnvironmentMutations';

export function useEnvironmentWorkspace(
  operationId: string | null,
  onOperation: (id: string) => void,
) {
  const loadCatalog = useCallback((signal: AbortSignal) => api.environments(signal), []);
  const catalog = useResource('environment-catalog', loadCatalog);
  const [choice, setChoice] = useState(operationId);
  const [previousRoute, setPreviousRoute] = useState(operationId);
  if (previousRoute !== operationId) {
    setPreviousRoute(operationId);
    setChoice(operationId);
  }
  const id =
    catalog.data?.active_operation?.id ?? choice ?? catalog.data?.operations[0]?.id ?? null;
  const loadOperation = useCallback(
    (signal: AbortSignal) => api.environmentOperation(id ?? '', signal),
    [id],
  );
  const operation = useResource(id ? `environment-operation:${id}` : null, loadOperation, {
    milliseconds: 1500,
    while: activeEnvironmentOperation,
  });
  const [lastKnown, setLastKnown] = useState(operation.data);
  if (operation.data && operation.data !== lastKnown) setLastKnown(operation.data);
  const selected =
    operation.data ??
    (lastKnown?.id === id ? lastKnown : null) ??
    [catalog.data?.active_operation, ...(catalog.data?.operations ?? [])].find(
      (item) => item?.id === id,
    ) ??
    null;
  const observed = useRef<string | null>(null);
  const refreshCatalog = catalog.reload,
    refreshOperation = operation.reload;
  const refresh = useCallback(() => {
    refreshCatalog();
    refreshOperation();
  }, [refreshCatalog, refreshOperation]);
  const choose = useCallback(
    (next: string) => {
      setChoice(next);
      onOperation(next);
    },
    [onOperation],
  );
  const mutations = useEnvironmentMutations(choose, refresh);
  useEffect(() => {
    if (
      selected &&
      !activeEnvironmentOperation(selected) &&
      observed.current !== `${selected.id}:${selected.status}`
    ) {
      observed.current = `${selected.id}:${selected.status}`;
      refreshCatalog();
    }
  }, [selected, refreshCatalog]);
  return { catalog, operation, selectionId: id, selected, choose, refresh, mutations };
}
