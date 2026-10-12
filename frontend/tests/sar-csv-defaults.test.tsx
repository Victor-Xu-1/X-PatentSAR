import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { decodeCSVPreview } from '../src/api/sarDecoders';
import { CSVMappingForm } from '../src/features/sar/CSVMappingForm';
import { initialMapping } from '../src/features/sar/csvMapping';
import { setLocale } from '../src/i18n';
import { csvPreview } from './sar-fixtures';

const preview = {
  ...csvPreview,
  headers: ['Compound ID', 'SMILES', 'IC50 (nM)', 'MW', 'Assay', 'PDF Page'],
  suggested_id: 'Compound ID',
  suggested_smiles: 'SMILES',
  suggested_activities: ['IC50 (nM)'],
  samples: [],
  mapping_defaults: {
    columns: { assay_column: 'Assay', source_page_column: 'PDF Page' },
    property_columns: { molecular_weight: 'MW' },
    prediction_columns: {},
    ambiguous_roles: [],
  },
};
beforeEach(() => setLocale('en'));
describe('source-owned CSV defaults', () => {
  it('uses typed server hints without a second client header matcher', () => {
    expect(decodeCSVPreview(preview)).toEqual(preview);
    const draft = initialMapping(preview);
    expect(draft).toMatchObject({
      id_column: 'Compound ID',
      smiles_column: 'SMILES',
      activity_columns: ['IC50 (nM)'],
      assay_column: 'Assay',
      source_page_column: 'PDF Page',
      property_columns: { molecular_weight: 'MW' },
    });
    expect(
      initialMapping({
        ...preview,
        mapping_defaults: { ...preview.mapping_defaults, columns: {}, property_columns: {} },
      }).assay_column,
    ).toBeNull();
  });
  it('rejects invented columns, duplicate roles and undeclared prediction keys', () => {
    for (const mapping_defaults of [
      { ...preview.mapping_defaults, columns: { assay_column: 'invented' } },
      { ...preview.mapping_defaults, columns: { assay_column: 'IC50 (nM)' } },
      { ...preview.mapping_defaults, property_columns: { invented: 'MW' } },
      { ...preview.mapping_defaults, prediction_columns: { hERG: 'MW' } },
    ])
      expect(() => decodeCSVPreview({ ...preview, mapping_defaults })).toThrow();
  });
  it('imports confident defaults with one deliberate submit and keeps all raw headers', async () => {
    const onSubmit = vi.fn();
    render(<CSVMappingForm preview={preview} disabled={false} onSubmit={onSubmit} />);
    expect(screen.getByLabelText('Source identifier column')).toHaveValue('Compound ID');
    expect(screen.getByLabelText('SMILES column')).toHaveValue('SMILES');
    expect(screen.getByRole('checkbox', { name: 'IC50 (nM)' })).toBeChecked();
    expect(onSubmit).not.toHaveBeenCalled();
    await userEvent.click(screen.getByRole('button', { name: 'Create CSV dataset' }));
    expect(onSubmit).toHaveBeenCalledWith(
      expect.objectContaining({
        assay_column: 'Assay',
        source_page_column: 'PDF Page',
        property_columns: { molecular_weight: 'MW' },
        activity_columns: ['IC50 (nM)'],
      }),
    );
  });
  it('does not replace an explicitly unresolved server identifier with a client guess', () => {
    render(
      <CSVMappingForm
        preview={{ ...preview, suggested_id: null }}
        disabled={false}
        onSubmit={vi.fn()}
      />,
    );
    expect(screen.getByLabelText('Source identifier column')).toHaveValue('');
    expect(screen.getByRole('button', { name: 'Create CSV dataset' })).toBeDisabled();
  });
});
