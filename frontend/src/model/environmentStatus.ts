import type {
  EnvironmentComponent,
  EnvironmentComponentId,
  EnvironmentComponentStatus,
} from '../api/environmentTypes';
import { environmentStatusLabels, selectedEnvironmentComponents } from './environment';

export function isEnvironmentComponentReady(component: EnvironmentComponent): boolean {
  return (
    component.status === 'ready' &&
    component.presence === 'present' &&
    component.verification === 'current'
  );
}

function hasMissingDependencies(component: EnvironmentComponent): boolean {
  return (
    component.status === 'missing' &&
    component.presence === 'present' &&
    component.verification === 'current'
  );
}

export function hasEnvironmentComponentFailure(component: EnvironmentComponent): boolean {
  return (
    ['partial', 'incompatible', 'error'].includes(component.status) ||
    hasMissingDependencies(component)
  );
}

export function environmentComponentBadge(component: EnvironmentComponent): {
  label: string;
  tone: EnvironmentComponentStatus;
} {
  if (hasMissingDependencies(component)) return { label: '缺少依赖', tone: 'partial' };
  if (component.status === 'checking' || hasEnvironmentComponentFailure(component))
    return { label: environmentStatusLabels[component.status], tone: component.status };
  if (isEnvironmentComponentReady(component)) return { label: '已安装·已验证', tone: 'ready' };
  if (component.presence === 'present')
    return {
      label: component.verification === 'stale' ? '已存在·待复检' : '已存在·待检测',
      tone: 'unchecked',
    };
  if (component.presence === 'missing' || component.presence === 'unconfigured')
    return { label: environmentStatusLabels[component.presence], tone: component.presence };
  return {
    label: component.verification === 'stale' ? '状态未知·待复检' : '状态未知·待检测',
    tone: 'unchecked',
  };
}

export function environmentComponentAction(
  component: EnvironmentComponent,
): 'installed' | 'inspect' | 'install' | 'repair' {
  if (isEnvironmentComponentReady(component)) return 'installed';
  if (component.status === 'checking') return 'inspect';
  if (hasEnvironmentComponentFailure(component))
    return component.presence === 'present' && component.verification === 'current'
      ? 'repair'
      : 'inspect';
  return component.presence === 'missing' || component.presence === 'unconfigured'
    ? 'install'
    : 'inspect';
}

export function canInstallEnvironmentPlan(components: EnvironmentComponent[]): boolean {
  return (
    components.length > 0 &&
    components.some((component) => !isEnvironmentComponentReady(component)) &&
    components.every((component) => {
      if (isEnvironmentComponentReady(component)) return true;
      const action = environmentComponentAction(component);
      return component.installable && (action === 'install' || action === 'repair');
    })
  );
}

export function environmentBundleAction(
  components: EnvironmentComponent[],
): 'ready' | 'inspect' | 'install' {
  if (components.length > 0 && components.every(isEnvironmentComponentReady)) return 'ready';
  if (
    components.some((component) => {
      const action = environmentComponentAction(component);
      return action === 'inspect' || action === 'repair';
    })
  )
    return 'inspect';
  return 'install';
}

export function isEnvironmentInstallPlanCurrent(
  planned: EnvironmentComponent[],
  requested: EnvironmentComponentId[],
  inventory: EnvironmentComponent[],
): boolean {
  let current: EnvironmentComponent[];
  try {
    current = selectedEnvironmentComponents(inventory, requested);
  } catch {
    return false;
  }
  const consentFields = [
    'id',
    'version',
    'license',
    'source_url',
    'download_bytes',
    'location',
    'presence',
    'verification',
    'status',
    'installable',
  ] as const;
  return (
    canInstallEnvironmentPlan(current) &&
    current.length === planned.length &&
    planned.every((component, index) => {
      const observed = current[index];
      return (
        observed !== undefined &&
        consentFields.every((field) => component[field] === observed[field])
      );
    })
  );
}
