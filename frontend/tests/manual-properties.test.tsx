import { render, screen } from '@testing-library/react';
import { describe, expect, it } from 'vitest';
import { decodeCompound } from '../src/api/decoders';
import { PredictionCells } from '../src/features/results/PredictionCells';
import { effectiveProperty } from '../src/model/propertyValues';
import { resultColumns } from '../src/model/resultColumns';
import { tableCopyText } from '../src/model/tableCopy';
import { changeStructureDraft, correctionDraft } from '../src/features/results/correctionDraft';
import { compound } from './fixtures';

describe('one effective manual-property presentation', () => {
  it('clears values when returning to the initial graph after editing a different graph', () => {
    const initial = correctionDraft({
      display_id: 'Compound 1',
      smiles: 'CCO',
      activities: [],
      structure_molfile: null,
      property_overrides: { molecular_weight: 46 },
      property_basis_smiles: 'CCO',
    });
    const first = changeStructureDraft(initial, {
      smiles: 'CCN',
      molfile: null,
      graphKey: 'CCN',
      graphChanged: true,
    });
    first.properties.molecular_weight = { value: '45', overridden: true, touched: true };
    const back = changeStructureDraft(first, {
      smiles: 'CCO',
      molfile: null,
      graphKey: 'CCO',
      graphChanged: false,
    });
    expect(back.properties.molecular_weight).toEqual({
      value: '',
      overridden: false,
      touched: false,
    });
    const coordinates = changeStructureDraft(initial, {
      smiles: 'CCO',
      molfile: 'coordinates',
      graphKey: 'CCO',
      graphChanged: false,
    });
    expect(coordinates.properties).toEqual(initial.properties);
  });
  it('renders all six finite manually entered values without inventing a model observation', () => {
    const row = decodeCompound({
      ...compound,
      property_overrides: {
        molecular_weight: 345.5,
        logP: -1.2,
        tpsa: 80.1,
        hydrogen_bond_donors: 2,
        hydrogen_bond_acceptors: 4,
        Solubility_AqSolDB: -4.3,
      },
    });
    render(
      <table>
        <tbody>
          <tr>
            <PredictionCells row={row} />
          </tr>
        </tbody>
      </table>,
    );
    for (const value of ['345.50', '-1.20', '80.10', '2', '4', '-4.30'])
      expect(screen.getByText(value)).toBeVisible();
    expect(row.admet).toBeUndefined();
    expect(effectiveProperty(row, 'logP')).toEqual({ value: -1.2, manual: true });
    const columns = resultColumns().filter((column) => column.id.startsWith('property:'));
    expect(tableCopyText([row], columns, [])).toBe(
      'MW\tLogP\tTPSA\tHBD\tHBA\tLogS\n345.5\t-1.2\t80.1\t2\t4\t-4.3',
    );
  });
  it('keeps an explicit manual blank blank even when a computed value is present', () => {
    const row = { ...compound, property_overrides: { logP: null } };
    expect(effectiveProperty(row, 'logP')).toEqual({ value: null, manual: true });
    render(
      <table>
        <tbody>
          <tr>
            <PredictionCells row={row} />
          </tr>
        </tbody>
      </table>,
    );
    expect(screen.getByLabelText('LogP 手工留空')).toBeVisible();
    expect(
      tableCopyText(
        [row],
        resultColumns().filter((column) => column.id === 'property:logP'),
        [],
      ),
    ).toBe('LogP\n');
  });
  it('does not insert additive fields into a raw source row', () => {
    expect(decodeCompound(compound)).toEqual(compound);
    expect(effectiveProperty(compound, 'molecular_weight')).toEqual({ value: null, manual: false });
  });
});
