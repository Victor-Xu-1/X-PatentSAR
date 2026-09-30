import { describe, expect, it } from 'vitest';
import {
  decodeEnvironmentCatalog,
  decodeEnvironmentOperation,
  matchesEnvironmentRequest,
} from '../src/api/environmentDecoders';
import type { EnvironmentComponentId } from '../src/api/environmentTypes';
import { selectedEnvironmentComponents } from '../src/model/environment';
import { environmentOperation, prerequisiteCatalog } from './environment-fixtures';

describe('server-declared prerequisite closure', () => {
  it('includes installer before base, even when the prerequisite is already ready', () => {
    const catalog = prerequisiteCatalog();
    expect(
      selectedEnvironmentComponents(catalog.components, ['base']).map((item) => item.id),
    ).toEqual(['installer', 'base']);
  });
  it('includes the actual SDK download and no unrelated runtime for a model-only selection', () => {
    const catalog = prerequisiteCatalog();
    const plan = selectedEnvironmentComponents(catalog.components, ['admet-models']);
    expect(plan.map((item) => item.id)).toEqual(['installer', 'admet', 'admet-models']);
    expect(plan.map((item) => item.download_bytes)).toContain(1_400_000_000);
    expect(plan.map((item) => item.id)).not.toContain('base');
    expect(plan.map((item) => item.id)).not.toContain('decimer');
  });
  it('deduplicates overlapping bundle prerequisites in deterministic execution order', () => {
    const catalog = prerequisiteCatalog();
    expect(
      selectedEnvironmentComponents(catalog.components, ['admet-models', 'base', 'admet']).map(
        (item) => item.id,
      ),
    ).toEqual(['installer', 'admet', 'admet-models', 'base']);
  });
  it('rejects unknown, missing, self, cyclic, duplicate and oversized dependencies before confirmation', () => {
    const catalog = prerequisiteCatalog();
    for (const dependencies of [
      ['cuda'],
      ['base'],
      ['installer', 'installer'],
      Array.from({ length: 7 }, () => 'installer'),
    ]) {
      const invalid = catalog.components.map((item) =>
        item.id === 'base'
          ? { ...item, dependencies: dependencies as EnvironmentComponentId[] }
          : item,
      );
      expect(() => selectedEnvironmentComponents(invalid, ['base'])).toThrow();
    }
    expect(() =>
      selectedEnvironmentComponents(
        catalog.components.filter((item) => item.id !== 'installer'),
        ['base'],
      ),
    ).toThrow();
    const cyclic = catalog.components.map((item) =>
      item.id === 'installer' ? { ...item, dependencies: ['base' as const] } : item,
    );
    expect(() => selectedEnvironmentComponents(cyclic, ['base'])).toThrow();
    expect(() =>
      selectedEnvironmentComponents([...catalog.components, catalog.components[0]!], ['base']),
    ).toThrow();
  });
  it('decodes required dependency metadata without discarding or fabricating it', () => {
    const catalog = prerequisiteCatalog();
    expect(decodeEnvironmentCatalog(catalog).components[1]?.dependencies).toEqual(['installer']);
    const absent = catalog.components.map(({ dependencies: omitted, ...item }) => {
      void omitted;
      return item;
    });
    expect(() => decodeEnvironmentCatalog({ ...catalog, components: absent })).toThrow('契约');
    for (const dependencies of [
      ['cuda'],
      ['installer', 'installer'],
      Array.from({ length: 7 }, () => 'installer'),
    ]) {
      expect(() =>
        decodeEnvironmentCatalog({
          ...catalog,
          components: catalog.components.map((item) =>
            item.id === 'base' ? { ...item, dependencies } : item,
          ),
        }),
      ).toThrow('契约');
    }
  });
  it('continues rejecting the real reported bug and accepts the resolved execution set', () => {
    expect(() =>
      decodeEnvironmentOperation({
        ...environmentOperation,
        component_ids: ['base'],
        completed_components: ['installer'],
      }),
    ).toThrow('契约');
    expect(
      decodeEnvironmentOperation({
        ...environmentOperation,
        component_ids: ['installer', 'base'],
        completed_components: ['installer'],
      }),
    ).toEqual(environmentOperation);
    const request = {
      action: 'install' as const,
      component_ids: ['installer' as const, 'base' as const],
      request_id: environmentOperation.request_id,
      expected_revision: 3,
    };
    expect(matchesEnvironmentRequest(environmentOperation, request)).toBe(true);
    expect(
      matchesEnvironmentRequest(
        { ...environmentOperation, component_ids: ['installer', 'base', 'admet'] },
        request,
      ),
    ).toBe(false);
    expect(
      matchesEnvironmentRequest(
        { ...environmentOperation, action: 'inspect' },
        { ...request, action: 'inspect', component_ids: ['base'] },
      ),
    ).toBe(false);
  });
});
