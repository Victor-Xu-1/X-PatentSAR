import { useTranslation } from '../../i18n';
import type { ActivityFocus, BBox } from '../../api/types';

export function pageBoxStyle([x1, y1, x2, y2]: BBox, width: number, height: number) {
  return {
    left: `${(100 * x1) / width}%`,
    top: `${(100 * y1) / height}%`,
    width: `${(100 * (x2 - x1)) / width}%`,
    height: `${(100 * (y2 - y1)) / height}%`,
  };
}
export function ActivityFocusMarks({
  focus,
  width,
  height,
}: {
  focus: ActivityFocus;
  width: number;
  height: number;
}) {
  const { t } = useTranslation();
  return focus.boxes.map((box, index) => (
    <span
      key={index}
      className="activity-focus-box"
      data-activity-focus={focus.activity_key}
      data-focus-compound={focus.compound_id}
      role="note"
      aria-label={t('活性原文定位 {index} / {total}', {
        index: index + 1,
        total: focus.boxes.length,
      })}
      style={pageBoxStyle(box, width, height)}
    />
  ));
}
