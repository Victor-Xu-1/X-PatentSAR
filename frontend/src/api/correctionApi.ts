import type { ApiClient } from './client';
import type { CorrectionDocument, EditableFields } from './correctionTypes';
import { decodeCorrection } from './correctionDecoders';

export function correctionApi(client: ApiClient) {
  const path = (id: string, compound: string) =>
    `/projects/${encodeURIComponent(id)}/structures/${encodeURIComponent(compound)}/correction`;
  return {
    getCorrection: (id: string, compound: string, signal: AbortSignal) =>
      client.get(path(id, compound), decodeCorrection, signal),
    saveCorrection: (
      id: string,
      compound: string,
      document: CorrectionDocument,
      fields: EditableFields,
    ) =>
      client.mutate(
        path(id, compound),
        'PUT',
        {
          expected_revision: document.revision,
          expected_source_fingerprint: document.source_fingerprint,
          fields,
        },
        decodeCorrection,
      ),
  };
}
