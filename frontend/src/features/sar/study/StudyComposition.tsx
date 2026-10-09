import type { StudyBin } from '../../../api/sarStudyTypes';
import { useTranslation } from '../../../i18n';
import { chartColor, compactBinLabel, composition } from './chartPresentation';
import type { CountingUnit } from './chartPresentation';

export function StudyComposition({
  bins,
  unit,
  layout,
  direction = 'lower',
}: {
  bins: StudyBin[];
  unit: CountingUnit;
  layout: 'donut' | 'stack';
  direction?: 'lower' | 'higher' | undefined;
}) {
  const { t } = useTranslation();
  const { total, parts } = composition(bins, unit);
  if (!total) return <div className="sar-chart-empty">{t('无分布记录')}</div>;
  if (layout === 'stack')
    return (
      <figure className="sar-composition-column" aria-label={t('活性分档组成')}>
        <strong className="sar-composition-total">{total}</strong>
        <div
          className="sar-composition-stack"
          role="graphics-object"
          aria-label={parts
            .filter((part) => part.share > 0)
            .map((part) => part.bin.label + ': ' + part.bin[unit])
            .join(' · ')}
        >
          {parts
            .filter((part) => part.share > 0)
            .map(({ bin, index, share }) => (
              <span
                key={bin.kind + ':' + bin.label}
                style={{
                  flexBasis: share * 100 + '%',
                  background: chartColor(bin, index, direction),
                }}
                title={bin.label + ' · ' + bin[unit] + ' / ' + total}
              />
            ))}
        </div>
        <figcaption>{t(unit === 'molecules' ? '原始编号 / 记录' : '观察数')}</figcaption>
      </figure>
    );
  const circumference = 2 * Math.PI * 46;
  return (
    <figure className="sar-composition-donut" aria-label={t('活性分档组成')}>
      <svg
        viewBox="0 0 128 128"
        aria-label={parts
          .filter((part) => part.share > 0)
          .map((part) => part.bin.label + ': ' + part.bin[unit])
          .join(' · ')}
      >
        {parts
          .filter((part) => part.share > 0)
          .map(({ bin, index, share }, partIndex, visible) => {
            const start = visible
              .slice(0, partIndex)
              .reduce((sum, part) => sum + part.share * circumference, 0);
            return (
              <circle
                key={bin.kind + ':' + bin.label}
                cx="64"
                cy="64"
                r="46"
                fill="none"
                stroke={chartColor(bin, index, direction)}
                strokeWidth="17"
                strokeDasharray={`${share * circumference} ${circumference}`}
                strokeDashoffset={-start}
                transform="rotate(-90 64 64)"
              >
                <title>{bin.label + ' · ' + bin[unit]}</title>
              </circle>
            );
          })}
        <text x="64" y="65" textAnchor="middle" className="sar-donut-number">
          {total}
        </text>
        <text x="64" y="82" textAnchor="middle" className="sar-donut-unit">
          {t(unit === 'molecules' ? '来源记录' : '观察数')}
        </text>
      </svg>
      <figcaption className="sr-only">{t('完整分布，缺失与冲突单独保留')}</figcaption>
    </figure>
  );
}

export function ChartLegend({
  bins,
  direction = 'lower',
  visibleBins,
}: {
  bins: StudyBin[];
  direction?: 'lower' | 'higher' | undefined;
  visibleBins?: readonly StudyBin[] | undefined;
}) {
  const { t } = useTranslation();
  const visible = visibleBins && new Set(visibleBins.map((bin) => bin.kind + ':' + bin.label));
  if (visible?.size === 0) return null;
  return (
    <ul className="sar-chart-legend" aria-label={t('活性图例')}>
      {bins.map((bin, index) =>
        !visible || visible.has(bin.kind + ':' + bin.label) ? (
          <li key={bin.kind + ':' + bin.label} title={bin.label}>
            <span style={{ background: chartColor(bin, index, direction) }} />
            {['missing', 'unsupported', 'unresolved'].includes(bin.kind)
              ? t(
                  bin.label === 'missing'
                    ? '无活性记录'
                    : bin.label === 'unsupported'
                      ? '未支持读数'
                      : '重复读数未确定',
                )
              : compactBinLabel(bin.label, bin.kind)}
          </li>
        ) : null,
      )}
    </ul>
  );
}
