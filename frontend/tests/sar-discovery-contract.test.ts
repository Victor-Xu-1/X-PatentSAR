import { describe, expect, it } from 'vitest';
import { decodeStudyDiscovery } from '../src/api/sarStudyDiscoveryDecoder';

const legacy = {
  method: 'single-non-ring-bond-v1',
  candidate_sites: 1,
  candidate_comparisons: 2,
  indexed_cuts: 3,
  excluded: {},
  max_variable_atoms: 32,
  max_variable_fraction: 0.4,
  min_fixed_atoms: 6,
  limitations: ['implicit_h_not_enumerated', 'ring_multiport_not_enumerated'],
};
const current = {
  ...legacy,
  method: 'single-region-one-two-cut-v2',
  max_cut_bonds: 2,
  examined_boundaries: 10,
  limitations: [
    'implicit_h_not_enumerated',
    'aromatic_boundaries_not_cut',
    'more_than_two_ports_not_enumerated',
  ],
};

describe('explicit legacy and one/two-port discovery coverage', () => {
  it('preserves legacy payload shape and never upgrades its boundary coverage', () => {
    expect(decodeStudyDiscovery(legacy)).toEqual(legacy);
    expect(() => decodeStudyDiscovery({ ...legacy, max_cut_bonds: 2 })).toThrow();
  });
  it('accepts complete current method metadata without changing source limits', () => {
    expect(decodeStudyDiscovery(current)).toEqual(current);
  });
  it.each([
    { ...current, max_cut_bonds: undefined },
    { ...current, max_cut_bonds: 1 },
    { ...current, examined_boundaries: undefined },
    { ...current, examined_boundaries: 500001 },
    { ...current, examined_boundaries: true },
    { ...current, max_variable_atoms: 500 },
    { ...current, method: 'unrestricted' },
  ])('refuses missing, wrong or over-budget scientific coverage', (payload) => {
    expect(() => decodeStudyDiscovery(payload)).toThrow();
  });
});
