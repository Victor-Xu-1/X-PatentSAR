import type { StereoEvidence } from './types';
import { array, boolean, ContractError, count, object, oneOf, string } from './validation';
import type { Decoder } from './validation';
import { decodeBBox } from './geometryDecoders';

const shape = object({
  version: count,
  image_sha256: string,
  image_size: array(count),
  unknown_bond_boxes: array(decodeBBox),
  status: oneOf(['no_unknown_detected', 'unknown_preserved', 'conflict', 'ambiguous']),
  reason: string,
  assigned_centers: count,
  unassigned_centers: count,
  assigned_double_bonds: count,
  absolute_configuration_verified: boolean,
});

export const decodeStereoEvidence: Decoder<StereoEvidence> = (input, path = '$') => {
  const value = shape(input, path);
  if (
    ![1, 2].includes(value.version) ||
    !/^[a-f0-9]{64}$/.test(value.image_sha256) ||
    value.image_size.length !== 2 ||
    value.image_size.some((n) => n < 8) ||
    value.image_size[0]! * value.image_size[1]! > 16 * 1024 * 1024 ||
    value.unknown_bond_boxes.length > 64 ||
    value.reason.length > 512 ||
    value.assigned_centers > 512 ||
    value.unassigned_centers > 512 ||
    value.assigned_double_bonds > 768 ||
    value.absolute_configuration_verified ||
    value.unknown_bond_boxes.some(
      (box) =>
        box[0] < 0 || box[1] < 0 || box[2] > value.image_size[0]! || box[3] > value.image_size[1]!,
    )
  )
    throw new ContractError(path);
  return value as StereoEvidence;
};
