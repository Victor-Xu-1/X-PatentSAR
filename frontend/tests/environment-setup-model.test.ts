import { describe, expect, it } from 'vitest';
import { canInstallEnvironmentPlan } from '../src/model/environmentStatus';
import {
  canSetupEnvironmentPlan,
  environmentSetupComponents,
  isEnvironmentSetupPlanCurrent,
} from '../src/model/environmentSetup';
import { completeEnvironmentCatalog, readyEnvironmentCatalog } from './environment-setup-fixtures';

describe('complete-scope authorization is separate from expert component installation', () => {
  it('uses the published dependency order and includes both scientific runtimes and models', () => {
    const catalog = completeEnvironmentCatalog();
    const plan = environmentSetupComponents(catalog);
    expect(plan.map((component) => component.id)).toEqual(catalog.setup_component_ids);
    expect(plan.map((component) => component.id)).toContain('admet');
    expect(plan.map((component) => component.id)).toContain('admet-models');
    expect(plan.map((component) => component.id)).toContain('molscribe');
    expect(plan.map((component) => component.id)).toContain('molscribe-models');
    expect(plan).toHaveLength(8);
  });
  it.each(['unchecked', 'stale'] as const)(
    'allows %s verification for complete rechecking but not advanced reinstall',
    (verification) => {
      const catalog = completeEnvironmentCatalog();
      catalog.components = catalog.components.map((component) => ({
        ...component,
        status: 'unchecked',
        presence: 'present',
        verification,
      }));
      const plan = environmentSetupComponents(catalog);
      expect(canSetupEnvironmentPlan(plan)).toBe(true);
      expect(canInstallEnvironmentPlan(plan)).toBe(false);
    },
  );
  it('retains every ready dependency for backend reuse without requiring it to be installable', () => {
    const catalog = readyEnvironmentCatalog();
    catalog.components = catalog.components.map((component) => ({
      ...component,
      installable: component.id === 'admet-models',
      ...(component.id === 'admet-models'
        ? {
            status: 'missing' as const,
            presence: 'missing' as const,
            verification: 'unchecked' as const,
          }
        : {}),
    }));
    const plan = environmentSetupComponents(catalog);
    expect(canSetupEnvironmentPlan(plan)).toBe(true);
    expect(plan).toHaveLength(8);
  });
  it('refuses an already-ready complete setup and unsupported deficiencies', () => {
    expect(canSetupEnvironmentPlan(environmentSetupComponents(readyEnvironmentCatalog()))).toBe(
      false,
    );
    const catalog = completeEnvironmentCatalog();
    catalog.components = catalog.components.map((component) =>
      component.id === 'base' ? { ...component, installable: false } : component,
    );
    expect(canSetupEnvironmentPlan(environmentSetupComponents(catalog))).toBe(false);
  });
  it('rejects truncated, duplicate, wrongly ordered and cyclic full plans', () => {
    const catalog = completeEnvironmentCatalog();
    for (const setup_component_ids of [
      [],
      catalog.setup_component_ids.slice(0, 4),
      [...catalog.setup_component_ids, catalog.setup_component_ids[0]!],
      [...catalog.setup_component_ids].reverse(),
    ])
      expect(() => environmentSetupComponents({ ...catalog, setup_component_ids })).toThrow();
    const cyclic = {
      ...catalog,
      components: catalog.components.map((component) =>
        component.id === 'installer'
          ? { ...component, dependencies: ['base' as const] }
          : component,
      ),
    };
    expect(() => environmentSetupComponents(cyclic)).toThrow('循环');
  });
  it('invalidates confirmation on name/version/download/source metadata changes', () => {
    const catalog = completeEnvironmentCatalog();
    const plan = environmentSetupComponents(catalog);
    expect(isEnvironmentSetupPlanCurrent(plan, catalog.setup_component_ids, catalog)).toBe(true);
    for (const changes of [
      { name: 'changed-name' },
      { version: 'changed-version' },
      { download_bytes: 999 },
      { source_url: 'https://example.invalid/changed' },
    ]) {
      const changed = {
        ...catalog,
        components: catalog.components.map((component) =>
          component.id === 'base' ? { ...component, ...changes } : component,
        ),
      };
      expect(isEnvironmentSetupPlanCurrent(plan, catalog.setup_component_ids, changed)).toBe(false);
    }
  });
});
