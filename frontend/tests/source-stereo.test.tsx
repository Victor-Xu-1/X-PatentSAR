import { render, screen } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';
import type { CompoundRecognition, StereoEvidence } from '../src/api/types';
import { decodeStereoEvidence } from '../src/api/stereoDecoders';
import { CropDialog } from '../src/features/results/CropDialog';
import { RecognitionDetails } from '../src/features/results/RecognitionDetails';
import { recognitionText, redrawPlaceholder } from '../src/model/results';
import { compound } from './fixtures';

const stereo: StereoEvidence = {
  version: 1,
  image_sha256: 'a'.repeat(64),
  image_size: [200, 100],
  unknown_bond_boxes: [[20, 40, 80, 60]],
  status: 'conflict',
  reason: 'unknown source and assigned graph',
  assigned_centers: 1,
  unassigned_centers: 0,
  assigned_double_bonds: 0,
  absolute_configuration_verified: false,
};
const recognition: CompoundRecognition = {
  status: 'invalid',
  quality_flag: 'stereo_source_conflict',
  model_fingerprint: 'b'.repeat(64),
  token_confidence: null,
  stereochemistry: stereo,
};

describe('source stereochemistry, not model certainty', () => {
  it('decodes bounded real observations without claiming absolute correctness', () => {
    expect(decodeStereoEvidence(stereo)).toEqual(stereo);
    expect(decodeStereoEvidence({ ...stereo, version: 2 })).toEqual({ ...stereo, version: 2 });
    expect(decodeStereoEvidence({ ...stereo, version: 3 })).toEqual({ ...stereo, version: 3 });
    for (const changes of [
      { version: 4 },
      { absolute_configuration_verified: true },
      { unknown_bond_boxes: [[0, 0, 300, 200]] },
      { image_sha256: 'fake' },
      { assigned_centers: -1 },
    ])
      expect(() => decodeStereoEvidence({ ...stereo, ...changes })).toThrow();
  });
  it('names stereo conflicts without incorrectly calling valid syntax unparsable', () => {
    expect(recognitionText(recognition)).toBe('手性冲突');
    expect(redrawPlaceholder({ ...compound, smiles: 'C[C@H](O)F', recognition })).toContain(
      '原图手性',
    );
    render(<RecognitionDetails recognition={recognition} />);
    expect(screen.getByText('未知键与确定构型冲突')).toBeVisible();
  });
  it('does not redraw an unresolved assigned candidate as accepted chemistry', () => {
    render(
      <CropDialog
        compound={{ ...compound, smiles: 'C[C@H](O)F', recognition }}
        projectId="test"
        onClose={vi.fn()}
      />,
    );
    expect(screen.getByText('原图手性与模型结果未能一致，需修正后重绘')).toBeVisible();
    expect(screen.queryByAltText(`${compound.display_id} 的 SMILES 重绘（非原图）`)).toBeNull();
  });
  it('does not promote absence of a wave hit or historical missing evidence', () => {
    render(
      <RecognitionDetails
        recognition={{
          ...recognition,
          stereochemistry: { ...stereo, status: 'no_unknown_detected' },
        }}
      />,
    );
    expect(screen.getByText('未发现未知键；不代表绝对构型已验证')).toBeVisible();
  });
});
