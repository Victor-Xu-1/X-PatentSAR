import type { Activity } from './types';
import type { PropertyOverrides } from './manualPropertyTypes';

export interface EditableFields {
  display_id: string;
  smiles: string | null;
  activities: Activity[];
  structure_molfile?: string | null;
  property_overrides?: PropertyOverrides;
  property_basis_smiles?: string | null;
}
export interface CorrectionDocument {
  source_fingerprint: string;
  revision: number;
  basis_fingerprint: string | null;
  stale: boolean;
  has_changes: boolean;
  original: EditableFields;
  values: EditableFields;
  updated_at: string | null;
}
