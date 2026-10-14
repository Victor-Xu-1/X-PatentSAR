import { act, fireEvent, render, screen } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';
import { decodeCompound } from '../src/api/decoders';
import { CompoundCell } from '../src/features/results/CompoundCell';
import { correctionDraft, draftFields } from '../src/features/results/correctionDraft';
import { setLocale } from '../src/i18n';
import { compoundLabel } from '../src/model/compoundLabel';
import { resultColumns } from '../src/model/resultColumns';
import { tableCopyText } from '../src/model/tableCopy';
import { compound } from './fixtures';

describe('patent-owned presentation label and stable internal identity', () => {
  const pending = {
    ...compound,
    id: 'source-structure:' + 'a'.repeat(32),
    display_id: '编号待确认 S0007',
    structure_id: 'S0007',
    record_kind: 'structure_only' as const,
    activities: [],
    flags: ['unassociated_structure', 'structure_number_unconfirmed'],
  };

  it('localizes only the generated unconfirmed source label and preserves correction identity', () => {
    const before = structuredClone(pending);
    setLocale('en');
    expect(compoundLabel(pending)).toBe('Identifier unconfirmed S0007');
    expect(
      tableCopyText(
        [pending],
        resultColumns().filter((column) => column.id === 'compound'),
        [],
      ),
    ).toBe('Original ID\n' + pending.display_id);
    const fields = {
      display_id: pending.display_id,
      smiles: null,
      structure_molfile: null,
      activities: [],
      property_overrides: {},
      property_basis_smiles: null,
    };
    const draft = correctionDraft(fields, pending);
    expect(draftFields(draft).display_id).toBe(pending.display_id);
    setLocale('zh-CN');
    expect(compoundLabel(pending)).toBe(pending.display_id);
    expect(draftFields(draft).display_id).toBe(pending.display_id);
    expect(pending).toEqual(before);
  });

  it('switches the real cell label and accessibility name without changing callbacks', () => {
    const details = vi.fn();
    render(
      <table>
        <tbody>
          <tr>
            <CompoundCell row={pending} onDetails={details} />
          </tr>
        </tbody>
      </table>,
    );
    act(() => setLocale('en'));
    const button = screen.getByRole('button', {
      name: 'View Identifier unconfirmed S0007 structure details',
    });
    expect(button).toHaveTextContent('Identifier unconfirmed S0007');
    fireEvent.click(button);
    expect(details).toHaveBeenCalledWith(pending);
    act(() => setLocale('zh-CN'));
    expect(screen.getByRole('button', { name: '查看 编号待确认 S0007 结构详情' })).toBeVisible();
  });

  it('never translates an original or user-edited label that resembles generated copy', () => {
    setLocale('en');
    for (const row of [
      { ...pending, identifier_label: pending.display_id },
      { ...pending, id: 'Compound 7' },
      { ...pending, flags: [] },
      {
        ...pending,
        correction: { revision: 1, stale: false, has_changes: true, updated_at: '2026-10-01' },
      },
      { ...pending, display_id: '编号待确认 User label' },
    ])
      expect(compoundLabel(row)).toBe(row.identifier_label ?? row.display_id);
  });

  it.each(['1', 'Example 008a', 'I-03B', '化合物 8B'])(
    'renders and copies %s without adding Compound',
    (label) => {
      const row = {
        ...compound,
        id: 'Compound 1',
        display_id: 'Compound 1',
        identifier_label: label,
      };
      const decoded = decodeCompound(row);
      const details = vi.fn();
      render(
        <table>
          <tbody>
            <tr>
              <CompoundCell row={decoded} onDetails={details} />
            </tr>
          </tbody>
        </table>,
      );
      const button = screen.getByRole('button', { name: `查看 ${label} 结构详情` });
      expect(button).toHaveTextContent(label);
      fireEvent.click(button);
      expect(details).toHaveBeenCalledWith(decoded);
      expect(decoded.id).toBe('Compound 1');
      expect(
        tableCopyText(
          [decoded],
          resultColumns().filter((column) => column.id === 'compound'),
          [],
        ),
      ).toBe(`原文编号\n${label}`);
    },
  );
  it('preserves older API and unconfirmed labels without guessing an identifier', () => {
    expect(compoundLabel(compound)).toBe(compound.display_id);
    expect(compoundLabel({ ...compound, identifier_label: null })).toBe(compound.display_id);
    expect(() => decodeCompound({ ...compound, identifier_label: 123 })).toThrow();
  });
  it('editing a metric does not implicitly rename the canonical correction field', () => {
    const row = {
      ...compound,
      id: 'Compound 008A',
      display_id: 'Compound 008A',
      identifier_label: 'Example 008A',
    };
    const fields = {
      display_id: row.display_id,
      smiles: 'CCO',
      structure_molfile: null,
      activities: row.activities,
      property_overrides: {},
      property_basis_smiles: null,
    };
    const draft = correctionDraft(fields, row);
    expect(draft.displayId).toBe('Example 008A');
    draft.properties.logP = { value: '3.2', touched: true, overridden: false };
    expect(draftFields(draft)).toMatchObject({
      display_id: 'Compound 008A',
      property_overrides: { logP: 3.2 },
    });
    draft.displayId = 'Example 008B';
    expect(draftFields(draft).display_id).toBe('Example 008B');
  });
});
