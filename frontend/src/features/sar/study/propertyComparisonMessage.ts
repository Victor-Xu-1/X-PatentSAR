import type { PropertyComparisonStatus } from '../../../api/sarStudyTypes';

const messages: Partial<Record<PropertyComparisonStatus, string>> = {
  missing: '未提供性质值',
  origin_unknown: '性质来源未确认',
  origin_mismatch: '性质来源不同',
  not_representable: '性质差值不可表示',
};

export function propertyComparisonMessage(status: PropertyComparisonStatus | undefined) {
  return status ? messages[status] : undefined;
}
