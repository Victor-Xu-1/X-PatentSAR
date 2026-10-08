import { describe, expect, it } from 'vitest';
import { readFileSync, readdirSync } from 'node:fs';
import { resolve } from 'node:path';
import { englishCatalog } from '../src/i18n/catalog';
import { workbench } from '../src/i18n/catalogs/workbench';
import { strengthScaleText } from '../src/model/activityStrength';
import { filterLabels } from '../src/model/columnFilters';
import { stageLabel, stageStatusText } from '../src/model/extraction';
import { setupWorkbenchLocale, switchTo } from './i18n-workbench-fixtures';

setupWorkbenchLocale();

describe('English workbench view and live language continuity', () => {
  it('recomputes direct stage/color presentation without capturing a locale in source-label records', () => {
    const scale = {
      kind: 'numeric' as const,
      direction: 'lower' as const,
      rule: 'potency' as const,
      eligible: 9,
      excluded: 2,
      distinct: 9,
      strong_boundary: 3,
      medium_boundary: 6,
    };
    expect(strengthScaleText(scale)).toContain('Lower is stronger');
    expect(stageLabel('structures')).toBe('Structure segmentation');
    expect(stageStatusText(null, undefined)).toBe('Not started');
    expect(filterLabels.contains).toBe('包含');
    switchTo('zh-CN');
    expect(strengthScaleText(scale)).toContain('越小越强');
    expect(stageLabel('structures')).toBe('结构分割');
    switchTo('en');
    expect(strengthScaleText(scale)).toContain('9 valid observations, 2 unranked');
    expect(filterLabels.contains).toBe('包含');
  });
  it('covers all marked owned source literals and preserves named placeholders in the literal-only catalog', () => {
    const root = resolve('src') + '/';
    const directories = [
      'features/results',
      'features/pdf',
      'features/analysis',
      'features/workspace',
      'features/structure-editor',
    ];
    const models = [
      'activityStrength',
      'columnFilters',
      'columnValueSelection',
      'resultColumns',
      'results',
      'extraction',
      'tableCopy',
    ];
    const files = [
      ...directories.flatMap((directory) =>
        readdirSync(root + directory)
          .filter((name) => /\.tsx?$/.test(name))
          .map((name) => root + directory + '/' + name),
      ),
      ...models.map((name) => root + 'model/' + name + '.ts'),
    ];
    const protocolOrIdentifier = new Set(['排序', '筛选', '未关联结构 ']);
    for (const path of files) {
      for (const [, , source] of readFileSync(path, 'utf8').matchAll(
        /(['"])([^'"\\\r\n]*[\u3400-\u9fff][^'"\\\r\n]*)\1/g,
      )) {
        if (!protocolOrIdentifier.has(source!))
          expect(englishCatalog[source!], `${path}: ${source}`).toBeTypeOf('string');
      }
    }
    const placeholders = (value: string) =>
      [...value.matchAll(/\{([A-Za-z][A-Za-z0-9_]*)\}/g)].map((match) => match[1]).sort();
    for (const [source, english] of Object.entries(workbench)) {
      expect(english, source).not.toMatch(/[\u3400-\u9fff]/u);
      expect(placeholders(english), source).toEqual(placeholders(source));
    }
    for (const name of ['table', 'chemistry', 'pdf', 'evidence']) {
      const catalogSource = readFileSync(root + `i18n/catalogs/${name}.ts`, 'utf8');
      expect(catalogSource).not.toMatch(/^import\s/m);
    }
    const assembly = readFileSync(root + 'i18n/catalogs/workbench.ts', 'utf8');
    expect(assembly).toContain("from '../catalogMerge'");
    expect(assembly).not.toContain("from '../catalog'");
  });
});
