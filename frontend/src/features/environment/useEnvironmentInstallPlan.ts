import { UiError } from '../../i18n';
import { useState } from 'react';
import type { EnvironmentCatalog, EnvironmentComponentId } from '../../api/environmentTypes';
import { selectedEnvironmentComponents } from '../../model/environment';
import {
  canInstallEnvironmentPlan,
  isEnvironmentInstallPlanCurrent,
} from '../../model/environmentStatus';
import {
  canSetupEnvironmentPlan,
  environmentSetupComponents,
  isEnvironmentSetupPlanCurrent,
} from '../../model/environmentSetup';
import type { InstallPlan } from './InstallConfirmation';

export function useEnvironmentInstallPlan(data: EnvironmentCatalog | null, disabled: boolean) {
  const [plan, setPlan] = useState<InstallPlan | null>(null);
  const [error, setError] = useState<Error | null>(null);
  const current = Boolean(
    plan &&
    data &&
    !disabled &&
    (plan.scope === 'complete'
      ? isEnvironmentSetupPlanCurrent(plan.components, plan.requested, data)
      : isEnvironmentInstallPlanCurrent(plan.components, plan.requested, data.components)),
  );
  function select(ids: EnvironmentComponentId[], scope: InstallPlan['scope']) {
    if (!data || disabled) return;
    setError(null);
    try {
      const components =
        scope === 'complete'
          ? environmentSetupComponents(data)
          : selectedEnvironmentComponents(data.components, ids);
      if (
        !(scope === 'complete'
          ? canSetupEnvironmentPlan(components)
          : canInstallEnvironmentPlan(components))
      )
        throw new UiError(
          '所选组件已安装、需先检测或不支持安装，请核对组件详情；不重复安装已有组件。',
        );
      setPlan({ components, settings: { ...data.settings }, requested: [...ids], scope });
    } catch (error) {
      setError(error instanceof Error ? error : new UiError('安装选择无效。'));
    }
  }
  return {
    plan,
    error,
    current,
    close: () => setPlan(null),
    setup: () => select(data?.setup_component_ids ?? [], 'complete'),
    install: (ids: EnvironmentComponentId[]) => select(ids, 'components'),
  };
}
