import { UiError } from '../i18n';
import type {
  EnvironmentCatalog,
  EnvironmentComponent,
  EnvironmentComponentId,
} from '../api/environmentTypes';
import { environmentComponentIds } from '../api/environmentTypes';
import { selectedEnvironmentComponents } from './environment';
import { environmentPlansMatch, isEnvironmentComponentReady } from './environmentStatus';

// The published plan is authoritative. The allowlist bounds/validates it, never supplies a fallback plan.
export function environmentSetupComponents(catalog: EnvironmentCatalog): EnvironmentComponent[] {
  const ids = catalog.setup_component_ids;
  if (
    !ids?.length ||
    catalog.components.length !== environmentComponentIds.length ||
    ids.length !== catalog.components.length ||
    new Set(ids).size !== ids.length
  )
    throw new UiError('服务端未提供有效的完整部署计划，请刷新或更新匹配的后端。');
  const plan = selectedEnvironmentComponents(catalog.components, ids);
  if (plan.length !== ids.length || plan.some((component, index) => component.id !== ids[index]))
    throw new UiError('服务端完整部署计划未包含正确顺序的全部前置依赖。');
  return plan;
}

export function canSetupEnvironmentPlan(components: EnvironmentComponent[]): boolean {
  return (
    components.length > 0 &&
    !components.every(isEnvironmentComponentReady) &&
    components.every(
      (component) =>
        isEnvironmentComponentReady(component) ||
        (component.installable && component.status !== 'checking'),
    )
  );
}

export function isEnvironmentSetupPlanCurrent(
  planned: EnvironmentComponent[],
  requested: EnvironmentComponentId[],
  catalog: EnvironmentCatalog,
): boolean {
  let current: EnvironmentComponent[];
  try {
    current = environmentSetupComponents(catalog);
  } catch {
    return false;
  }
  return (
    requested.length === catalog.setup_component_ids.length &&
    requested.every((id, index) => id === catalog.setup_component_ids[index]) &&
    canSetupEnvironmentPlan(current) &&
    environmentPlansMatch(planned, current)
  );
}
