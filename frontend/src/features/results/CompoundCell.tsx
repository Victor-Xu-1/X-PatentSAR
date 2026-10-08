import { useTranslation } from '../../i18n';
import type { Compound } from '../../api/types';
import { compoundLabel } from '../../model/compoundLabel';

export function CompoundCell({
  row,
  onDetails,
}: {
  row: Compound;
  onDetails: (row: Compound) => void;
}) {
  const { t } = useTranslation();
  const corrected = Boolean(row.correction?.has_changes && !row.correction.stale && row.smiles);
  const label = compoundLabel(row);
  const displayLabel =
    row.record_kind === 'structure_only' &&
    label.startsWith('未关联结构 ') &&
    (!row.correction?.has_changes || row.correction.stale)
      ? label.replace(/ · p\.\d+$/, '')
      : label;
  return (
    <td className="compound-column frozen-column frozen-compound">
      <div className="compound-identity">
        <button
          type="button"
          className="compound-detail-button"
          data-focus-key={`detail:${row.id}`}
          aria-label={t('查看 {label} 结构详情', { label })}
          title={label}
          onClick={() => onDetails(row)}
        >
          {displayLabel}
        </button>
        {row.correction?.stale ? (
          <small className="correction">{t('待重核')}</small>
        ) : row.correction?.has_changes ? (
          <small className="correction">{corrected ? t('已修正 · 重绘') : t('已修正')}</small>
        ) : null}
        {row.record_kind === 'activity_only' && <small className="muted">{t('结构待定位')}</small>}
        {row.record_kind === 'structure_only' && !row.activities.length && (
          <small className="muted">
            {row.flags.includes('structure_number_unconfirmed')
              ? t('编号待确认')
              : t('暂无活性数据')}
          </small>
        )}
      </div>
    </td>
  );
}
