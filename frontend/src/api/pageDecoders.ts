import type { ActivityFocus, PageData } from './types';
import {
  array,
  boolean,
  ContractError,
  nullable,
  number,
  object,
  oneOf,
  positive,
  string,
} from './validation';
import type { Decoder } from './validation';
import { decodeBBox } from './geometryDecoders';
import { activitySourceKey, validFocusCompound } from './activitySourceDecoders';

const focusShape = object({
  compound_id: string,
  activity_key: activitySourceKey,
  status: oneOf(['located', 'page_only']),
  boxes: array(decodeBBox),
  message: nullable(string),
});
const pageShape = object({
  page: positive,
  page_count: positive,
  width: nullable(number),
  height: nullable(number),
  image_url: nullable(string),
  text: string,
  source_mode: oneOf(['native', 'ocr', 'historical', 'unavailable']),
  annotations: array(
    object({ compound_id: string, bbox: decodeBBox, kind: string, verified: boolean }),
  ),
});
function decodeFocus(input: unknown, page: PageData, path: string): ActivityFocus {
  // Check the bounded list before parsing its contents.
  if (typeof input !== 'object' || input === null || Array.isArray(input))
    throw new ContractError(path);
  const boxes = (input as Record<string, unknown>).boxes;
  if (!Array.isArray(boxes) || boxes.length > 80) throw new ContractError(path + '.boxes');
  const focus = focusShape(input, path);
  if (
    !validFocusCompound(focus.compound_id) ||
    (focus.status === 'located' ? !focus.boxes.length : focus.boxes.length !== 0)
  )
    throw new ContractError(path);
  if (focus.status === 'located') {
    if (
      !page.image_url ||
      page.width === null ||
      page.height === null ||
      page.width <= 0 ||
      page.height <= 0
    )
      throw new ContractError(path + '.boxes');
    for (const box of focus.boxes)
      if (box[2] > page.width || box[3] > page.height) throw new ContractError(path + '.boxes');
  }
  return focus;
}
export const decodePage: Decoder<PageData> = (input, path = '$') => {
  const page = pageShape(input, path);
  if (
    page.page > page.page_count ||
    (page.width !== null && page.width <= 0) ||
    (page.height !== null && page.height <= 0)
  )
    throw new ContractError(path);
  const fields = input as Record<string, unknown>;
  if (!Object.hasOwn(fields, 'activity_focus')) return page;
  return {
    ...page,
    activity_focus:
      fields.activity_focus === null
        ? null
        : decodeFocus(fields.activity_focus, page, path + '.activity_focus'),
  };
};
