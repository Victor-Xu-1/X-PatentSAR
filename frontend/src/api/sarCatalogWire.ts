import { ContractError, count, string } from './validation';

// The existing full-report transport/domain bound, not a sampling or region limit.
const LIMIT = 32 * 1024 * 1024;
const encoder = new TextEncoder();
type RecordValue = Record<string, unknown>;

function record(value: unknown, path: string): RecordValue {
  if (typeof value !== 'object' || value === null || Array.isArray(value))
    throw new ContractError(path);
  return value as RecordValue;
}
function list(value: unknown, path: string, maximum = LIMIT): unknown[] {
  if (!Array.isArray(value) || value.length > maximum) throw new ContractError(path);
  return value;
}
function bytes(value: unknown, path: string): number {
  try {
    return encoder.encode(JSON.stringify(value)).byteLength;
  } catch {
    throw new ContractError(path);
  }
}
function index(value: unknown, length: number, path: string): number {
  const result = count(value, path);
  if (result >= length) throw new ContractError(path);
  return result;
}

/** Expand only the known wire identity, then use the sole ordinary domain decoder. */
export function expandCatalog(value: unknown, path: string): unknown {
  const input = record(value, path);
  if (input.detail === 'catalog') return value;
  if (input.detail !== 'catalog-pooled' || input.wire_version !== 1)
    throw new ContractError(path + '.detail');
  const members = list(input.molecule_id_pool, path + '.molecule_id_pool');
  const memberBytes = members.map((value, n) => {
    const p = `${path}.molecule_id_pool[${n}]`;
    list(value, p, 100_000).forEach((id, i) => string(id, `${p}[${i}]`));
    return bytes(value, p);
  });
  const fragments = list(input.fragment_pool, path + '.fragment_pool');
  const fragmentBytes = fragments.map((value, n) => {
    const p = `${path}.fragment_pool[${n}]`,
      fragment = record(value, p),
      member = index(fragment.molecule_ids, members.length, p + '.molecule_ids');
    // Count the member list without expanding a repeated list into a JSON string.
    return bytes({ ...fragment, molecule_ids: [] }, p) + memberBytes[member]! - 2;
  });
  const report = record(input.report, path + '.report');
  const regions = list(report.regions, path + '.report.regions', 100_000).map((value, n) => {
    const p = `${path}.report.regions[${n}]`,
      region = record(value, p);
    list(region.fragments, p + '.fragments', 100_000);
    return region;
  });
  const base: RecordValue = { ...input, detail: 'catalog', report: { ...report, regions: [] } };
  delete base.fragment_pool;
  delete base.molecule_id_pool;
  delete base.wire_version;
  let size = bytes(
    { ...base, report: { ...report, regions: regions.map((r) => ({ ...r, fragments: [] })) } },
    path,
  );
  // Validate the complete projected byte budget before allocating expanded uses.
  if (size > LIMIT) throw new ContractError(path + '.catalog_expansion');
  regions.forEach((region, n) => {
    const refs = region.fragments as unknown[];
    refs.forEach((ref, i) => {
      const p = `${path}.report.regions[${n}].fragments[${i}]`;
      size += fragmentBytes[index(ref, fragments.length, p)]! + (i === 0 ? 0 : 1);
      if (size > LIMIT) throw new ContractError(path + '.catalog_expansion');
    });
  });
  const expanded = fragments.map((value) => {
    const fragment = value as RecordValue;
    return { ...fragment, molecule_ids: members[fragment.molecule_ids as number] };
  });
  return {
    ...base,
    report: {
      ...report,
      regions: regions.map((region) => ({
        ...region,
        fragments: (region.fragments as number[]).map((ref) => expanded[ref]),
      })),
    },
  };
}
