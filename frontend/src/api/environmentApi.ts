import type { ApiClient } from './client';
import { ContractError } from './validation';
import {
  decodeEnvironmentCatalog,
  decodeEnvironmentOperation,
  decodeEnvironmentOperationId,
  decodeEnvironmentRequest,
  decodeEnvironmentSettings,
  matchesEnvironmentRequest,
} from './environmentDecoders';
import type { EnvironmentOperationRequest, EnvironmentStorageLocations } from './environmentTypes';

export function environmentApi(client: ApiClient) {
  const operationPath = (id: string) =>
    `/environments/operations/${encodeURIComponent(decodeEnvironmentOperationId(id))}`;
  const scoped = (id: string) => (value: unknown) => {
    const operation = decodeEnvironmentOperation(value);
    if (operation.id !== id) throw new ContractError('$.operation.id');
    return operation;
  };
  return {
    environments: (signal: AbortSignal) =>
      client.get('/environments', decodeEnvironmentCatalog, signal),
    updateEnvironmentSettings: (
      locations: EnvironmentStorageLocations | string,
      expected_revision: number,
    ) =>
      client.mutate(
        '/environments/settings',
        'PUT',
        {
          install_root: typeof locations === 'string' ? locations : locations.install_root,
          ...(typeof locations === 'string'
            ? {}
            : { upload_root: locations.upload_root, result_root: locations.result_root }),
          expected_revision,
        },
        decodeEnvironmentSettings,
      ),
    createEnvironmentOperation: (input: EnvironmentOperationRequest) => {
      const request = decodeEnvironmentRequest(input);
      return client.mutate('/environments/operations', 'POST', request, (value) => {
        const operation = decodeEnvironmentOperation(value);
        if (!matchesEnvironmentRequest(operation, request))
          throw new ContractError('$.operation.request');
        return operation;
      });
    },
    environmentOperation: (id: string, signal: AbortSignal) =>
      client.get(operationPath(id), scoped(id), signal),
    cancelEnvironmentOperation: (id: string) =>
      client.mutate(`${operationPath(id)}/cancel`, 'POST', {}, scoped(id)),
  };
}
