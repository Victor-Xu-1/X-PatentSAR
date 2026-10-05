import {
  array,
  boolean,
  ContractError,
  count,
  defaulted,
  nullable,
  object,
  oneOf,
  string,
} from './validation';
import type { Decoder } from './validation';
import type {
  EnvironmentCatalog,
  EnvironmentComponentId,
  EnvironmentOperation,
  EnvironmentOperationRequest,
  EnvironmentSettings,
} from './environmentTypes';
import { environmentComponentIds } from './environmentTypes';

const ids: Decoder<EnvironmentComponentId[]> = (value, path = '$') => {
  const result = array(oneOf(environmentComponentIds))(value, path);
  if (result.length > 6 || new Set(result).size !== result.length) throw new ContractError(path);
  return result;
};
export const decodeEnvironmentRequestId: Decoder<string> = (value, path = '$') => {
  const id = string(value, path);
  if (!/^[A-Za-z0-9_-]{16,64}$/.test(id)) throw new ContractError(path);
  return id;
};
export const decodeEnvironmentOperationId: Decoder<string> = (value, path = '$') => {
  const id = string(value, path);
  if (!/^[A-Za-z0-9_-]{1,200}$/.test(id)) throw new ContractError(path);
  return id;
};
export function matchesEnvironmentRequest(
  operation: EnvironmentOperation,
  request: EnvironmentOperationRequest,
): boolean {
  return (
    operation.request_id === request.request_id &&
    operation.action === request.action &&
    operation.component_ids.length === request.component_ids.length &&
    request.component_ids.every((id) => operation.component_ids.includes(id))
  );
}
export const decodeEnvironmentSettings: Decoder<EnvironmentSettings> = object({
  install_root: string,
  allowed_root: string,
  revision: count,
  enabled: boolean,
  reason: nullable(string),
});
const requestShape = object({
  action: oneOf(['inspect', 'install']),
  component_ids: ids,
  request_id: decodeEnvironmentRequestId,
  expected_revision: count,
});
export const decodeEnvironmentRequest: Decoder<EnvironmentOperationRequest> = (value, path) => {
  const result = requestShape(value, path);
  if (!result.component_ids.length) throw new ContractError('$.component_ids');
  return result;
};
const operationShape = object({
  id: decodeEnvironmentOperationId,
  request_id: decodeEnvironmentRequestId,
  action: oneOf(['inspect', 'install']),
  component_ids: ids,
  status: oneOf(['queued', 'running', 'complete', 'failed', 'cancelled', 'interrupted']),
  created_at: string,
  started_at: nullable(string),
  finished_at: nullable(string),
  install_root: string,
  stage: string,
  completed_components: ids,
  log_tail: array(string),
  error: nullable(object({ code: string, message: string })),
  applied: boolean,
});
export const decodeEnvironmentOperation: Decoder<EnvironmentOperation> = (value, path) => {
  const result = operationShape(value, path);
  if (
    !result.id ||
    !result.component_ids.length ||
    result.completed_components.some((id) => !result.component_ids.includes(id))
  )
    throw new ContractError('$.operation');
  return result;
};
const componentStatus = oneOf([
  'unchecked',
  'checking',
  'missing',
  'partial',
  'ready',
  'unconfigured',
  'incompatible',
  'error',
]);
const componentChecks = array(object({ name: string, ok: boolean, message: string }));
const component = object({
  id: oneOf(environmentComponentIds),
  name: string,
  description: string,
  version: string,
  detected_version: nullable(string),
  status: componentStatus,
  presence: defaulted(oneOf(['present', 'missing', 'unconfigured', 'unknown']), 'unknown'),
  verification: defaulted(oneOf(['current', 'stale', 'unchecked']), 'unchecked'),
  checked_at: defaulted(nullable(string), null),
  last_check: defaulted(
    nullable(
      object({
        status: componentStatus,
        detected_version: nullable(string),
        checked_at: nullable(string),
        checks: componentChecks,
        problem: nullable(string),
      }),
    ),
    null,
  ),
  location: nullable(string),
  kind: oneOf(['tool', 'runtime', 'models']),
  group: oneOf(['tools', 'base', 'structure', 'admet']),
  required: boolean,
  installable: boolean,
  download_bytes: nullable(count),
  installed_bytes: nullable(count),
  license: string,
  source_url: string,
  checks: componentChecks,
  problem: nullable(string),
  dependencies: ids,
});
const catalogShape = object({
  settings: decodeEnvironmentSettings,
  components: array(component),
  setup_component_ids: defaulted(ids, []),
  presets: array(object({ id: string, name: string, description: string, component_ids: ids })),
  checked_at: nullable(string),
  active_operation: nullable(decodeEnvironmentOperation),
  operations: array(decodeEnvironmentOperation),
});
export const decodeEnvironmentCatalog: Decoder<EnvironmentCatalog> = (value, path) => {
  const result = catalogShape(value, path);
  if (
    new Set(result.components.map((item) => item.id)).size !== result.components.length ||
    new Set(result.presets.map((item) => item.id)).size !== result.presets.length
  )
    throw new ContractError('$.catalog.identity');
  return result;
};
