import { useState } from 'react';
import type { Comparison, Dataset, MatchState, PairPage, Molecule } from '../../api/sarTypes';
import { useTranslation } from '../../i18n';
import { comparisonLabels, evidenceLabels, matchLabels } from './presentation';
import { SourceLinks } from './SourceLinks';
import { TableScroll } from './TableScroll';
export function PairTable({
  dataset,
  pairs,
  onSource,
  reference,
}: {
  dataset: Dataset;
  pairs: PairPage;
  onSource: (id: string) => void;
  reference?: Molecule | null;
}) {
  const { t } = useTranslation();
  const [match, setMatch] = useState<MatchState | ''>('');
  const [comparison, setComparison] = useState<Comparison | ''>('');
  const visible = pairs.items.filter(
    (pair) =>
      (!match || pair.match_status === match) && (!comparison || pair.comparison === comparison),
  );
  return (
    <>
      <div className="sar-form-grid">
        <label>
          {t('匹配筛选（当前页）')}
          <select value={match} onChange={(e) => setMatch(e.target.value as typeof match)}>
            <option value="">{t('全部状态')}</option>
            {Object.entries(matchLabels).map(([value, label]) => (
              <option key={value} value={value}>
                {t(label)}
              </option>
            ))}
          </select>
        </label>
        <label>
          {t('比较筛选（当前页）')}
          <select
            value={comparison}
            onChange={(e) => setComparison(e.target.value as typeof comparison)}
          >
            <option value="">{t('全部状态')}</option>
            {Object.entries(comparisonLabels).map(([value, label]) => (
              <option key={value} value={value}>
                {t(label)}
              </option>
            ))}
          </select>
        </label>
      </div>
      <p className="sar-hint">{t('筛选仅作用于服务器当前页；导出包含任务全部原始结果。')}</p>
      {!pairs.items.length && <p>{t('尚无比较结果')}</p>}
      {!!pairs.items.length && !visible.length && <p>{t('当前页没有匹配筛选的结果')}</p>}
      {!!visible.length && (
        <TableScroll label={t('参考比较结果')}>
          <table>
            <thead>
              <tr>
                <th>{t('原文编号')}</th>
                <th>{t('参考')}</th>
                <th>{t('结构匹配')}</th>
                <th>{t('活性比较')}</th>
                <th>{t('参考原值')}</th>
                <th>{t('待比较原值')}</th>
                <th>{t('原始数值比（非药效倍数）')}</th>
                <th>{t('证据依据')}</th>
                <th>{t('原始原因')}</th>
                <th>{t('来源详情')}</th>
              </tr>
            </thead>
            <tbody>
              {visible.map((pair) => (
                <tr key={pair.molecule_id}>
                  <th scope="row">{pair.label}</th>
                  <td>
                    <button
                      type="button"
                      aria-label={t('参考来源详情')}
                      onClick={() => onSource(pair.reference_id)}
                    >
                      {reference?.id === pair.reference_id ? reference.label : t('参考来源详情')}
                    </button>
                  </td>
                  <td>{t(matchLabels[pair.match_status])}</td>
                  <td>{t(comparisonLabels[pair.comparison])}</td>
                  <td>
                    {pair.reference_values.map((v, i) => (
                      <div key={i}>{v}</div>
                    ))}
                  </td>
                  <td>
                    {pair.candidate_values.map((v, i) => (
                      <div key={i}>{v}</div>
                    ))}
                  </td>
                  <td>{pair.fold_change === null ? '—' : String(pair.fold_change)}</td>
                  <td>{t(evidenceLabels[pair.evidence_basis])}</td>
                  <td>
                    <ul>
                      {pair.reasons.map((reason, i) => (
                        <li key={i}>{reason}</li>
                      ))}
                    </ul>
                  </td>
                  <td>
                    <SourceLinks dataset={dataset} />
                    <button type="button" onClick={() => onSource(pair.molecule_id)}>
                      {t('来源详情')}
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </TableScroll>
      )}
    </>
  );
}
