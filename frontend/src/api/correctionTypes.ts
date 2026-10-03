import type { Activity } from './types';

export interface EditableFields {
  display_id: string;
  smiles: string | null;
  activities: Activity[];
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
