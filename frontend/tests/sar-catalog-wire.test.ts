import { describe, expect, it } from 'vitest';
import { decodeStudyCatalog } from '../src/api/sarStudyDecoders';
import { expandCatalog } from '../src/api/sarCatalogWire';
import { catalogBody, coherentCatalogReport } from './sar-catalog-fixtures';

function packet(legacy = catalogBody()) {
  const members = legacy.report.regions[0]!.fragments.map((fragment) => fragment.molecule_ids);
  const fragments = legacy.report.regions[0]!.fragments.map((fragment, index) => ({
    ...fragment,
    molecule_ids: index,
  }));
  return {
    ...legacy,
    detail: 'catalog-pooled',
    wire_version: 1,
    fragment_pool: fragments,
    molecule_id_pool: members,
    report: {
      ...legacy.report,
      regions: legacy.report.regions.map((region) => ({
        ...region,
        fragments: region.fragments.map((_, index) => index),
      })),
    },
  };
}

describe('bounded lossless catalog wire transport', () => {
  it('expands the complete known wire through the same existing domain decoder', () => {
    expect(decodeStudyCatalog(packet())).toEqual(decodeStudyCatalog(catalogBody()));
    const current = catalogBody(coherentCatalogReport());
    expect(decodeStudyCatalog(packet(current))).toEqual(decodeStudyCatalog(current));
  });

  it('preserves same-ID differences, complete ordered membership and separate domain instances', () => {
    const legacy = catalogBody();
    const original = legacy.report.regions[0]!;
    const variants = [
      { molecule_ids: ['A', 'B'] },
      { molecule_ids: ['B', 'A'] },
      { molecule_ids: ['A', 'C'] },
      { molecule_count: 99 },
      { is_reference: false },
      { representation: 'aromatic_graph' as const },
    ].map((update) => ({ ...original.fragments[0]!, ...update }));
    legacy.report.regions = [0, 1, 2].map((n) => ({
      ...original,
      region: { ...original.region, id: n.toString(16).padStart(32, '0') },
      fragments: variants,
    }));
    const wire = packet(legacy),
      before = structuredClone(wire);
    const result = decodeStudyCatalog(wire);
    expect(result).toEqual(decodeStudyCatalog(legacy));
    expect(wire).toEqual(before);
    result.report.regions[0]!.fragments[0]!.molecule_ids.push('local mutation');
    expect(result.report.regions[1]!.fragments[0]!.molecule_ids).toEqual(['A', 'B']);
    expect(wire).toEqual(before);
  });

  it.each([-1, 1.5, true, '0', null, NaN, Infinity, 9007199254740992, 42])(
    'rejects malformed/outside fragment and member references: %s',
    (bad) => {
      for (const target of ['fragment', 'member']) {
        const wire = packet();
        if (target === 'fragment') wire.report.regions[0]!.fragments = [bad as number];
        else wire.fragment_pool[0]!.molecule_ids = bad as number;
        expect(() => decodeStudyCatalog(wire)).toThrow();
      }
    },
  );

  it('refuses unknown versions, malformed pools and invalid scientific identity after expansion', () => {
    for (const update of [
      { wire_version: 2 },
      { wire_version: '1' },
      { wire_version: true },
      { detail: 'catalog-v2' },
      { fragment_pool: null },
      { molecule_id_pool: null },
      { fragment_pool: [null] },
      { molecule_id_pool: [[null]] },
    ])
      expect(() => decodeStudyCatalog({ ...packet(), ...update })).toThrow();
    for (const target of ['count', 'source', 'membership', 'context']) {
      const wire = packet(catalogBody(coherentCatalogReport()));
      if (target === 'count') wire.fragment_pool[0]!.molecule_count = 8;
      if (target === 'source') wire.activity_basis.source_input_sha256 = 'f'.repeat(64);
      if (target === 'membership') wire.molecule_id_pool[1] = wire.molecule_id_pool[0]!;
      if (target === 'context') wire.report.policies[0]!.context_id = 'f'.repeat(64);
      expect(() => decodeStudyCatalog(wire)).toThrow();
    }
  });

  it('refuses expanded UTF-8 bytes over the existing 32 MiB bound before domain allocation', () => {
    const wire = packet();
    wire.fragment_pool[0]!.id = '💠'.repeat(4096);
    wire.report.regions[0]!.fragments = Array(2200).fill(0) as number[];
    expect(JSON.stringify(wire).length).toBeLessThan(100_000);
    expect(() => expandCatalog(wire, '$')).toThrow(/catalog_expansion/);
    // Shared member lists also count once per use, not once per pool entry.
    wire.fragment_pool[0]!.id = 'small';
    wire.molecule_id_pool[0] = Array(10).fill('A'.repeat(8192)) as string[];
    wire.report.regions[0]!.fragments = Array(500).fill(0) as number[];
    expect(() => expandCatalog(wire, '$')).toThrow(/catalog_expansion/);
  });
});
