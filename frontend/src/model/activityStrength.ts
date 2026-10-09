import { t } from '../i18n';
import type { ActivityStrengthScale } from '../api/types';

export type ActivityStrength = 'strong' | 'medium' | 'none';

export function activityStrength(
  value: number | null | undefined,
  scale: ActivityStrengthScale | null | undefined,
): ActivityStrength {
  if (
    value === null ||
    value === undefined ||
    !Number.isFinite(value) ||
    !scale ||
    scale.method === 'tenth_decade' ||
    (scale.status && scale.status !== 'ready') ||
    scale.direction === 'unknown' ||
    scale.eligible === 0 ||
    scale.strong_boundary === null ||
    scale.medium_boundary === null
  )
    return 'none';
  if (scale.direction === 'lower') {
    if (value <= scale.strong_boundary) return 'strong';
    if (value <= scale.medium_boundary) return 'medium';
  } else {
    if (value >= scale.strong_boundary) return 'strong';
    if (value >= scale.medium_boundary) return 'medium';
  }
  return 'none';
}

export const activityStrengthLabels = {
  strong: '本列相对强档',
  medium: '本列中档',
  none: '本列其余或未分档',
};

export function strengthScaleText(scale: ActivityStrengthScale): string {
  if (scale.method === 'tenth_decade') {
    if (scale.status !== 'ready')
      return t(
        scale.status === 'insufficient'
          ? '不足十个化合物，未分档'
          : scale.status === 'ambiguous'
            ? '第十名数量级不确定，未分档'
            : scale.status === 'limit'
              ? '超过上色统计限额，保留原值但不着色'
              : '该指标不适用浓度倍数分档',
      );
    return t(
      '第十名数量级；强 <{strong}，中 {strong}–<{medium}，弱 ≥{medium}。全任务计算，筛选和翻页不改变分档。',
      { strong: scale.strong_boundary!, medium: scale.medium_boundary! },
    );
  }
  if (scale.direction === 'unknown')
    return scale.rule === 'mixed_types'
      ? t('混合值类型，未自动分档')
      : scale.rule === 'limit'
        ? t('超过上色统计限额，保留原值但不着色')
        : t('活性强弱方向未确认，不自动着色');
  if (!scale.eligible) return t('没有可排序的有效值，不自动着色');
  const order =
    scale.kind === 'plus'
      ? t('按加号数量由多到少')
      : scale.kind === 'letter'
        ? t('按字母等级 A 优先')
        : scale.direction === 'lower'
          ? t('越小越强')
          : t('越大越强');
  const ties =
    scale.distinct < 3 ? t('不足三种取值，不强行凑齐三档') : t('按全项目排名近似三等分，并列同色');
  return t(
    '{order}；{eligible} 个有效观察，{excluded} 个未分档；{ties}。仅本列相对比较，不是绝对活性或验收结论；方向按指标约定，需对照原文定义。',
    { order, eligible: scale.eligible, excluded: scale.excluded, ties },
  );
}
