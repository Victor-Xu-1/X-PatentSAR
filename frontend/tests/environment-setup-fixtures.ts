import type { EnvironmentCatalog } from '../src/api/environmentTypes';
import { environmentCatalog } from './environment-fixtures';

export function completeEnvironmentCatalog(): EnvironmentCatalog {
  return {
    ...environmentCatalog,
    setup_component_ids: environmentCatalog.components.map((component) => component.id),
    components: environmentCatalog.components.map((component) => ({
      ...component,
      status: 'missing',
      presence: 'missing',
      verification: 'unchecked',
      checked_at: null,
      detected_version: null,
      last_check: null,
      checks: [],
      location: null,
      problem: null,
      installable: true,
    })),
  };
}
export function readyEnvironmentCatalog(): EnvironmentCatalog {
  const catalog = completeEnvironmentCatalog();
  return {
    ...catalog,
    components: catalog.components.map((component) => ({
      ...component,
      status: 'ready',
      presence: 'present',
      verification: 'current',
      checked_at: '2026-10-05T00:00:00Z',
      detected_version: component.version,
      location: '/srv/wsl/envs/actual-' + component.id,
      checks: [{ name: '实际检测', ok: true, message: '已核对' }],
    })),
  };
}
