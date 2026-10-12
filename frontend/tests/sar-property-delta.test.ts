import { expect, it } from 'vitest';
import { propertyDelta } from '../src/features/sar/study/propertyDelta';
import type { PropertyComparisonStatus } from '../src/api/sarStudyTypes';

function source(key: string, first: number, second: number, origin = 'computed_rdkit') {
  return {
    reference: { properties: { [key]: first }, property_origins: { [key]: origin } },
    candidate: { properties: { [key]: second }, property_origins: { [key]: origin } },
    property_differences: { [key]: second - first },
    property_statuses: { [key]: 'comparable' as PropertyComparisonStatus },
  };
}

it('labels both actual native-descriptor sources as approximate zero without changing raw data', () => {
  for (const [first, second] of [
    [137.11, 137.11000000000004],
    [137.11000000000004, 137.11],
  ]) {
    const data = source('tpsa', first!, second!);
    const original = JSON.stringify(data);
    const result = propertyDelta(data, 'tpsa');
    expect(result.text).toBe('≈ 0');
    expect(result.approximate).toBe(true);
    expect(result.raw).toBe((second! > first! ? '+' : '') + String(second! - first!));
    expect(JSON.stringify(data)).toBe(original);
    expect(
      propertyDelta(source('tpsa', first!, second!, 'verified_project_descriptor'), 'tpsa'),
    ).toEqual(result);
  }
});

it('keeps exact zero distinct from near-zero and preserves meaningful small native differences', () => {
  expect(propertyDelta(source('tpsa', 137.11, 137.11), 'tpsa')).toMatchObject({
    text: '0.00',
    approximate: false,
    raw: '0',
  });
  expect(
    propertyDelta(source('Solubility_AqSolDB', -5.74, -5.746154), 'Solubility_AqSolDB'),
  ).toMatchObject({ text: '-0.00615', approximate: false });
});

it('does not erase tiny imported, manual, modeled or unknown-origin differences', () => {
  for (const origin of ['imported', 'manual', 'verified_project_model', '', 'future']) {
    const result = propertyDelta(source('tpsa', 137.11, 137.11000000000004, origin), 'tpsa');
    expect(result.approximate).toBe(false);
    expect(result.text).toMatch(/^\+/);
    expect(result.text).not.toContain('≈');
  }
});

it('requires current comparable status, equal native provenance and exact raw subtraction before approximation', () => {
  const data = source('tpsa', 137.11, 137.11000000000004);
  for (const status of [undefined, 'origin_unknown', 'origin_mismatch'] as const) {
    const guarded = status
      ? { ...data, property_statuses: { tpsa: status } }
      : {
          reference: data.reference,
          candidate: data.candidate,
          property_differences: data.property_differences,
        };
    expect(propertyDelta(guarded, 'tpsa').approximate).toBe(false);
  }
  expect(
    propertyDelta(
      { ...data, candidate: { ...data.candidate, property_origins: { tpsa: 'manual' } } },
      'tpsa',
    ).approximate,
  ).toBe(false);
  expect(
    propertyDelta(
      { ...data, candidate: { ...data.candidate, properties: { tpsa: 138.11 } } },
      'tpsa',
    ).approximate,
  ).toBe(false);
});

it('never approximates count properties, unknown keys or differences outside the numerical bound', () => {
  for (const key of [
    'hydrogen_bond_donors',
    'hydrogen_bond_acceptors',
    'Solubility_AqSolDB',
    'IC50',
    'future',
  ])
    expect(propertyDelta(source(key, 137.11, 137.11000000000004), key).approximate).toBe(false);
  expect(propertyDelta(source('tpsa', 137.11, 137.110000001), 'tpsa').approximate).toBe(false);
});

it('preserves missing or nonfinite differences without manufacturing zero', () => {
  const data = source('tpsa', 137.11, 137.11);
  for (const value of [null, undefined, Infinity, NaN]) {
    const result = propertyDelta({ ...data, property_differences: { tpsa: value } }, 'tpsa');
    expect(result).toEqual({ text: '—', raw: null, approximate: false });
  }
});
