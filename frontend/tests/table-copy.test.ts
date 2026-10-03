import { describe, expect, it } from 'vitest';
import { METRIC_SPECS } from '../src/api/predictionTypes';
import type { Compound } from '../src/api/types';
import { resultColumns } from '../src/model/resultColumns';
import { safeTsvCell, tableCopyText } from '../src/model/tableCopy';
import { compound } from './fixtures';

describe('typed numeric cells retain spreadsheet numeric import semantics', () => {
  it.each([-4.93, -0.001, -1e100, -0, 0, 3.5, Number.MAX_VALUE])(
    'preserves finite numeric %s without a formula escape prefix',
    (value) => {
      expect(safeTsvCell(value)).toBe(String(value));
      expect(safeTsvCell(value)).not.toMatch(/^'/);
    },
  );
  it.each([
    '-4.93',
    '-1e100',
    '-SUM(A1)',
    ' -HYPERLINK("evil")',
    '\uFEFF-cmd',
    '\t-cmd',
    '=cmd',
    '+cmd',
    '@cmd',
  ])('still neutralizes string formula prefix %s', (value) => {
    expect(safeTsvCell(value)).toMatch(/^'/);
    expect(safeTsvCell(value)).not.toMatch(/[\p{Cc}\p{Zl}\p{Zp}]/u);
  });
  it('removes control and row separators without changing original strings', () => {
    const original = 'a\u0000b\tc\r\nd\u007fe\u2028f\u2029g';
    expect(safeTsvCell(original)).toBe('a b c d e f g');
    expect(original).toContain('\u0000');
    expect(safeTsvCell(undefined)).toBe('');
    expect(safeTsvCell(null)).toBe('');
  });
  it('does not treat nonfinite numbers as trusted numerical observations', () => {
    expect(safeTsvCell(-Infinity)).toBe("'-Infinity");
    expect(safeTsvCell(Infinity)).toBe('Infinity');
    expect(safeTsvCell(NaN)).toBe('NaN');
  });
  it('copies actual negative LogP and LogS properties at full precision without modifying the source row', () => {
    const values = [345.36, -1.2345, 87.99, 2, 4, -4.9123];
    const row: Compound = {
      ...compound,
      admet: {
        status: 'complete',
        properties: METRIC_SPECS.map((spec, index) => ({ ...spec, value: values[index]! })),
        source_fingerprint: null,
        smiles_sha256: null,
        engine: null,
        generated_at: null,
        job_id: null,
        warnings: [],
        error: null,
        review_only: true,
      },
    };
    const original = JSON.stringify(row);
    const columns = resultColumns().filter(
      (column) => column.id === 'property:logP' || column.id === 'property:Solubility_AqSolDB',
    );
    expect(tableCopyText([row], columns, [])).toBe('LogP\tLogS\n-1.2345\t-4.9123');
    expect(JSON.stringify(row)).toBe(original);
  });
});
