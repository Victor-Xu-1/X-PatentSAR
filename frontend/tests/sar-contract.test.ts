import { describe, expect, it } from 'vitest';
import {
  decodeCSVPreview,
  decodeDataset,
  decodeDrawing,
  decodeMolecules,
  decodeRegion,
} from '../src/api/sarDecoders';
import { decodePair, decodePairs, decodeSARJob } from '../src/api/sarJobDecoders';
import { gradeOrder, newRequestId } from '../src/features/sar/presentation';
import { initialMapping, mappingValid } from '../src/features/sar/csvMapping';
import { safeDrawing } from '../src/features/sar/safeDrawing';
import {
  csvPreview,
  sarDataset,
  sarDrawing,
  sarInvalid,
  sarJob,
  sarMolecule,
  sarPair,
  sarRegion,
} from './sar-fixtures';

describe('authoritative SAR DTO boundary', () => {
  it('decodes exact shared fixtures without hiding invalid rows or repeated observations', () => {
    expect(decodeDataset(sarDataset)).toEqual(sarDataset);
    expect(decodeDrawing(sarDrawing)).toEqual(sarDrawing);
    expect(decodeRegion(sarRegion)).toEqual(sarRegion);
    expect(decodeSARJob(sarJob)).toEqual(sarJob);
    expect(decodePair(sarPair)).toEqual(sarPair);
    expect(
      decodeMolecules({ items: [sarMolecule, sarInvalid], total: 3, page: 1, page_size: 50 }).items,
    ).toEqual([sarMolecule, sarInvalid]);
    expect(
      decodePairs({ items: [sarPair], total: 1, page: 1, page_size: 50, job: sarJob }).items[0]
        ?.reference_values,
    ).toEqual(['<10 nM', '<10 nM']);
  });
  it('keeps additive input record count distinct and old responses honestly unknown', () => {
    const { input_row_count: _count, ...old } = sarDataset;
    expect(decodeDataset(old)).not.toHaveProperty('input_row_count');
    expect(() => decodeDataset({ ...sarDataset, input_row_count: -1 })).toThrow();
    expect(decodeDataset(sarDataset).input_row_count).toBe(4);
    expect(decodeDataset(sarDataset).row_count).toBe(3);
  });
  it('keeps original document SHA separate from snapshot fingerprint and accepts omission/null safely', () => {
    const { source_document_sha256: _document, ...legacy } = sarDataset;
    expect(decodeDataset(legacy)).not.toHaveProperty('source_document_sha256');
    expect(
      decodeDataset({ ...sarDataset, source_document_sha256: null }).source_document_sha256,
    ).toBeNull();
    expect(decodeDataset(sarDataset).source_document_sha256).toBe('9'.repeat(64));
    expect(decodeDataset(sarDataset).source_sha256).toBe('a'.repeat(64));
    expect(() => decodeDataset({ ...sarDataset, source_document_sha256: 'invalid' })).toThrow();
  });
  it.each([-0.1, 1.1, NaN, Infinity])('rejects non-normalized atom coordinate %s', (x) => {
    expect(() =>
      decodeDrawing({ ...sarDrawing, atoms: [{ ...sarDrawing.atoms[0], x }] }),
    ).toThrow();
  });
  it('rejects duplicate atom indices, malformed graph identity, negative progress and invented statuses', () => {
    expect(() =>
      decodeDrawing({ ...sarDrawing, atoms: [sarDrawing.atoms[0], sarDrawing.atoms[0]] }),
    ).toThrow();
    expect(() => decodeRegion({ ...sarRegion, graph_sha256: 'legacy' })).toThrow();
    expect(() => decodeSARJob({ ...sarJob, processed: 4 })).toThrow();
    expect(() => decodeSARJob({ ...sarJob, status: 'accepted' })).toThrow();
    expect(() => decodePair({ ...sarPair, fold_change: 2 })).toThrow();
  });
  it('rejects mismatched preview headers and invalid sample fields', () => {
    expect(decodeCSVPreview(csvPreview)).toEqual(csvPreview);
    expect(() => decodeCSVPreview({ ...csvPreview, suggested_smiles: 'invented' })).toThrow();
    expect(() => decodeCSVPreview({ ...csvPreview, headers: ['id', 'id'] })).toThrow();
  });
});
describe('explicit CSV and grade conventions', () => {
  it('recognizes the native long CSV mapping and original context headers', () => {
    const draft = initialMapping(csvPreview);
    expect(draft).toMatchObject({
      id_column: 'identifier_label',
      smiles_column: 'smiles',
      activity_columns: ['value'],
      metric_column: 'metric',
      unit_column: 'unit',
      target_column: 'target',
      assay_column: 'assay',
    });
    expect(mappingValid(draft, csvPreview)).toBe(true);
  });
  it('keeps wide columns separate and unknown roles empty', () => {
    const preview = {
      ...csvPreview,
      headers: ['identifier', 'structure', 'raw x', 'raw y'],
      samples: [],
      suggested_id: null,
      suggested_smiles: null,
      suggested_activities: ['raw x', 'raw y'],
    };
    const draft = initialMapping(preview);
    expect(draft.metric_column).toBeNull();
    expect(draft.activity_columns).toEqual(['raw x', 'raw y']);
    expect(mappingValid(draft, preview)).toBe(false);
    expect(
      mappingValid({ ...draft, id_column: 'identifier', smiles_column: 'structure' }, preview),
    ).toBe(true);
  });
  it('never guesses grade order or creates non-crypto request identities', () => {
    expect(gradeOrder('')).toEqual({ values: [], valid: true });
    expect(gradeOrder('Strong\nModerate\nWeak')).toEqual({
      values: ['Strong', 'Moderate', 'Weak'],
      valid: true,
    });
    expect(gradeOrder('A\nA').valid).toBe(false);
    expect(gradeOrder(Array.from({ length: 33 }, (_, i) => String(i)).join('\n')).valid).toBe(
      false,
    );
    expect(newRequestId()).toMatch(/^[a-f0-9]{32}$/);
    expect(newRequestId()).not.toBe(newRequestId());
  });
});
describe('passive server SVG boundary', () => {
  it('keeps the actual RDKit canvas ratio and uses an image, not active DOM markup', () => {
    const result = safeDrawing(sarDrawing.svg);
    expect(result.aspectRatio).toBe('400 / 300');
    expect(decodeURIComponent(result.url)).toContain('bond-0 atom-0 atom-1');
    expect(result.url).toMatch(/^data:image\/svg\+xml/);
  });
  it.each([
    '<script>alert(1)</script>',
    '<foreignObject><div>unsafe</div></foreignObject>',
    '<image href="https://external.invalid/x"/>',
    '<path onclick="alert(1)"/>',
    '<path style="fill:url(https://external.invalid/x)"/>',
    '<a href="javascript:alert(1)">x</a>',
    '<animate attributeName="href"/>',
    '<path style="position:fixed"/>',
    '<path style="fill:u&#92;72l(/unsafe-resource)"/>',
  ])('rejects active or fetchable SVG %s', (inner) => {
    expect(() =>
      safeDrawing(
        `<svg xmlns="http://www.w3.org/2000/svg" width="400" height="300">${inner}</svg>`,
      ),
    ).toThrow();
  });
  it('rejects entities, malformed SVG and an unproved canvas', () => {
    expect(() => safeDrawing('<!DOCTYPE svg><svg xmlns="http://www.w3.org/2000/svg"/>')).toThrow();
    expect(() => safeDrawing('<svg')).toThrow();
    expect(() => safeDrawing('<svg xmlns="http://www.w3.org/2000/svg"/>')).toThrow();
  });
  it('accepts passive RDKit text fonts without allowing stylesheet or URL escapes', () => {
    expect(
      safeDrawing(
        '<svg xmlns="http://www.w3.org/2000/svg" width="400" height="300"><text x="20" y="30" style="font-size:20px;font-style:normal;font-family:sans-serif;fill:#000000">O</text></svg>',
      ).aspectRatio,
    ).toBe('400 / 300');
  });
});
