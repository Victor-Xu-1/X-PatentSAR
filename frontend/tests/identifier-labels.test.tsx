import { fireEvent, render, screen } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';
import { decodeCompound } from '../src/api/decoders';
import { CompoundCell } from '../src/features/results/CompoundCell';
import { correctionDraft, draftFields } from '../src/features/results/correctionDraft';
import { compoundLabel } from '../src/model/compoundLabel';
import { resultColumns } from '../src/model/resultColumns';
import { tableCopyText } from '../src/model/tableCopy';
import { compound } from './fixtures';

describe('patent-owned presentation label and stable internal identity', () => {
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
