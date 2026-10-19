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
  EnvironmentReuseSource,
} from './environmentTypes';
import { environmentComponentIds } from './environmentTypes';

const ids: Decoder<EnvironmentComponentId[]> = (value, path = '$') => {
  const result = array(oneOf(environmentComponentIds))(value, path);
  if (result.length > environmentComponentIds.length || new Set(result).size !== result.length)
    throw new ContractError(path);
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
    request.component_ids.every((id) => operation.component_ids.includes(id)) &&
    (request.action !== 'reuse' ||
      (Boolean(operation.reuse_source && request.reuse_source) &&
        operation.reuse_source?.python === request.reuse_source?.python &&
        operation.reuse_source?.models === request.reuse_source?.models))
  );
}
export const decodeEnvironmentSettings: Decoder<EnvironmentSettings> = object({
  install_root: string,
  upload_root: string,
  result_root: string,
  allowed_root: string,
  allowed_data_root: string,
  revision: count,
  editable: boolean,
  enabled: boolean,
  reason: nullable(string),
});
const requestShape = object({
  action: oneOf(['inspect', 'install', 'reuse']),
  component_ids: ids,
  request_id: decodeEnvironmentRequestId,
  expected_revision: count,
});
export const decodeEnvironmentReuseSource: Decoder<EnvironmentReuseSource> = (
  value,
  path = '$',
) => {
  const result = object({ python: string, models: string })(value, path);
  if (
    Object.keys(value as object)
      .sort()
      .join(',') !== 'models,python'
  )
    throw new ContractError(path);
  for (const [key, raw] of Object.entries(result)) {
    if (
      !raw.startsWith('/') ||
      raw.length > 512 ||
      raw === '/' ||
      /[\\:]/.test(raw) ||
      Array.from(raw).some(
        (character) => character.charCodeAt(0) < 32 || character.charCodeAt(0) === 127,
      ) ||
      raw.includes('//') ||
      raw.endsWith('/') ||
      raw.split('/').some((part) => part === '.' || part === '..') ||
      (key === 'python' && (raw === '/mnt' || raw.startsWith('/mnt/')))
    )
      throw new ContractError(path);
  }
  return result;
};
export const decodeEnvironmentRequest: Decoder<EnvironmentOperationRequest> = (value, path) => {
  const result = requestShape(value, path);
  if (!result.component_ids.length) throw new ContractError('$.component_ids');
  const raw = value as Record<string, unknown>;
  if (result.action === 'reuse') {
    if (
      result.component_ids.length !== 2 ||
      !['text-ocr', 'text-ocr-models'].every((id) =>
        result.component_ids.includes(id as EnvironmentComponentId),
      )
    )
      throw new ContractError('$.component_ids');
    return {
      ...result,
      reuse_source: decodeEnvironmentReuseSource(raw.reuse_source, '$.reuse_source'),
    };
  }
  if (raw.reuse_source != null) throw new ContractError('$.reuse_source');
  return result;
};
const operationShape = object({
  id: decodeEnvironmentOperationId,
  request_id: decodeEnvironmentRequestId,
  action: oneOf(['inspect', 'install', 'reuse']),
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
    result.completed_components.some((id) => !result.component_ids.includes(id)) ||
    (result.action === 'reuse' &&
      (result.component_ids.length !== 2 ||
        !result.component_ids.includes('text-ocr') ||
        !result.component_ids.includes('text-ocr-models')))
  )
    throw new ContractError('$.operation');
  const raw = value as Record<string, unknown>;
  if (result.action === 'reuse')
    return {
      ...result,
      reuse_source: decodeEnvironmentReuseSource(raw.reuse_source, '$.reuse_source'),
    };
  if (raw.reuse_source != null) throw new ContractError('$.reuse_source');
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
