export const environmentComponentIds = [
  'installer',
  'base',
  'decimer',
  'decimer-models',
  'admet',
  'admet-models',
] as const;
export type EnvironmentComponentId = (typeof environmentComponentIds)[number];
export type EnvironmentComponentStatus =
  | 'unchecked'
  | 'checking'
  | 'missing'
  | 'partial'
  | 'ready'
  | 'unconfigured'
  | 'incompatible'
  | 'error';
export interface EnvironmentComponent {
  id: EnvironmentComponentId;
  name: string;
  description: string;
  version: string;
  detected_version: string | null;
  status: EnvironmentComponentStatus;
  location: string | null;
  kind: 'tool' | 'runtime' | 'models';
  group: 'tools' | 'base' | 'structure' | 'admet';
  required: boolean;
  installable: boolean;
  download_bytes: number | null;
  installed_bytes: number | null;
  license: string;
  source_url: string;
  checks: { name: string; ok: boolean; message: string }[];
  problem: string | null;
}
export interface EnvironmentSettings {
  install_root: string;
  allowed_root: string;
  revision: number;
  enabled: boolean;
  reason: string | null;
}
export interface EnvironmentPreset {
  id: string;
  name: string;
  description: string;
  component_ids: EnvironmentComponentId[];
}
export interface EnvironmentOperationRequest {
  action: 'inspect' | 'install';
  component_ids: EnvironmentComponentId[];
  request_id: string;
  expected_revision: number;
}
export interface EnvironmentOperation {
  id: string;
  request_id: string;
  action: 'inspect' | 'install';
  component_ids: EnvironmentComponentId[];
  status: 'queued' | 'running' | 'complete' | 'failed' | 'cancelled' | 'interrupted';
  created_at: string;
  started_at: string | null;
  finished_at: string | null;
  install_root: string;
  stage: string;
  completed_components: EnvironmentComponentId[];
  log_tail: string[];
  error: { code: string; message: string } | null;
  applied: boolean;
}
export interface EnvironmentCatalog {
  settings: EnvironmentSettings;
  components: EnvironmentComponent[];
  presets: EnvironmentPreset[];
  checked_at: string | null;
  active_operation: EnvironmentOperation | null;
  operations: EnvironmentOperation[];
}
