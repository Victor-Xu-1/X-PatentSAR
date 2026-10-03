import type { BBox } from './types';
import { array, ContractError, number } from './validation';
import type { Decoder } from './validation';

export const decodeBBox: Decoder<BBox> = (input, path = '$') => {
  const values = array(number)(input, path);
  if (values.length !== 4) throw new ContractError(path);
  const [x1, y1, x2, y2] = values as BBox;
  if (x1 < 0 || y1 < 0 || x2 <= x1 || y2 <= y1) throw new ContractError(path);
  return [x1, y1, x2, y2];
};
