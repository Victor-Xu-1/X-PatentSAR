import type { Activity } from '../../api/types';
import type { EditableFields } from '../../api/correctionTypes';
import { decodeEditableFields } from '../../api/correctionDecoders';

export interface ActivityDraft {
  name: string;
  value: string;
  valueKind: 'number' | 'text';
  unit: string;
  target: string;
  assay: string;
  page: string;
}
export interface CorrectionDraft {
  displayId: string;
  smiles: string;
  activities: ActivityDraft[];
}
export function activityDraft(activity: Activity): ActivityDraft {
  return {
    name: activity.name,
    value: activity.value === null ? '' : String(activity.value),
    valueKind: typeof activity.value === 'number' ? 'number' : 'text',
    unit: activity.unit ?? '',
    target: activity.target ?? '',
    assay: activity.assay ?? '',
    page: activity.page === null ? '' : String(activity.page),
  };
}
export function correctionDraft(fields: EditableFields): CorrectionDraft {
  return {
    displayId: fields.display_id,
    smiles: fields.smiles ?? '',
    activities: fields.activities.map(activityDraft),
  };
}
export function draftFields(draft: CorrectionDraft): EditableFields {
  const optional = (text: string) => text.trim() || null;
  const activities = draft.activities.map((item) => {
    const value =
      item.value === '' ? null : item.valueKind === 'number' ? Number(item.value) : item.value;
    if (
      item.valueKind === 'number' &&
      item.value !== '' &&
      (!item.value.trim() || !Number.isFinite(value))
    )
      throw new Error('数值必须是有限数字；等级、范围或比较符请使用文本类型。');
    const page = item.page.trim() === '' ? null : Number(item.page);
    if (page !== null && (!Number.isSafeInteger(page) || page < 1 || page > 20000))
      throw new Error('来源页必须是 1–20000 的整数，或留空。');
    return {
      name: item.name.trim(),
      value,
      unit: optional(item.unit),
      target: optional(item.target),
      assay: optional(item.assay),
      page,
    };
  });
  return decodeEditableFields({
    display_id: draft.displayId.trim(),
    smiles: optional(draft.smiles),
    activities,
  });
}
