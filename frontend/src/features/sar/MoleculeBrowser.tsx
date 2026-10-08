import { useCallback, useState } from 'react';
import { sarApi } from '../../api/sarApi';
import type { Dataset, Molecule } from '../../api/sarTypes';
import { useResource } from '../../hooks/useResource';
import { useDebounced } from '../../hooks/useDebounced';
import { Empty, Loading } from '../../components/Feedback';
import { SARFailure } from './SARFailure';
import { useTranslation } from '../../i18n';
import { PageControls } from './PageControls';
import { SourceLinks } from './SourceLinks';
import { TableScroll } from './TableScroll';

export function MoleculeBrowser({
  dataset,
  active,
  referenceId,
  onReference,
}: {
  dataset: Dataset;
  active: boolean;
  referenceId: string | null;
  onReference: (molecule: Molecule) => void;
}) {
  const { t } = useTranslation();
  const [query, setQuery] = useState('');
  const [page, setPage] = useState(1);
  const search = useDebounced(query, 250);
  const load = useCallback(
    (signal: AbortSignal) => sarApi.molecules(dataset.id, page, search, signal),
    [dataset.id, page, search],
  );
  const resource = useResource(
    active ? `sar:rows:${dataset.id}:${dataset.revision}:${page}:${search}` : null,
    load,
  );
  return (
    <section className="sar-panel" aria-label={t('选择参考分子')}>
      <h2>{t('选择参考分子')}</h2>
      <label>
        {t('搜索编号或 SMILES')}
        <input
          type="search"
          maxLength={500}
          value={query}
          onChange={(e) => {
            setQuery(e.target.value);
            setPage(1);
          }}
        />
      </label>
      {resource.loading && <Loading />}
      {resource.error && <SARFailure error={resource.error} onRetry={resource.reload} />}
      {resource.data && (
        <>
          {!resource.data.items.length ? (
            <Empty title="没有匹配行" description="清除搜索以查看全部行，包括缺失或无效 SMILES。" />
          ) : (
            <TableScroll label={t('数据集所有行')}>
              <table>
                <thead>
                  <tr>
                    <th>{t('原文编号')}</th>
                    <th>SMILES</th>
                    <th>{t('原始活性')}</th>
                    <th>{t('行问题')}</th>
                    <th>{t('来源详情')}</th>
                    <th>{t('参考')}</th>
                  </tr>
                </thead>
                <tbody>
                  {resource.data.items.map((molecule) => (
                    <tr key={molecule.id} data-selected={referenceId === molecule.id}>
                      <th scope="row">{molecule.label}</th>
                      <td className="sar-chemistry">{molecule.smiles ?? t('未提供 SMILES')}</td>
                      <td>
                        {molecule.observations.map((observation, index) => (
                          <div key={index}>
                            {dataset.metrics.find((metric) => metric.id === observation.metric_id)
                              ?.name ?? observation.metric_id}
                            : {observation.value}
                            {observation.unit && <span> · {observation.unit}</span>}
                          </div>
                        ))}
                      </td>
                      <td>
                        {molecule.eligible ? t('可作为参考') : t('不可分析')}
                        <ul>
                          {molecule.issues.map((issue, i) => (
                            <li key={i}>{issue}</li>
                          ))}
                        </ul>
                      </td>
                      <td>
                        <SourceLinks dataset={dataset} molecule={molecule} />
                      </td>
                      <td>
                        <button
                          type="button"
                          disabled={dataset.stale || !molecule.eligible || !molecule.graph_sha256}
                          aria-pressed={referenceId === molecule.id}
                          onClick={() => onReference(molecule)}
                        >
                          {t('参考')}
                        </button>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </TableScroll>
          )}
          <PageControls
            page={page}
            total={resource.data.total}
            onPage={setPage}
            disabled={resource.loading}
          />
        </>
      )}
      <p className="sar-hint">{t('来源数据未经翻译；问题代码与原始原因保留服务器原文。')}</p>
    </section>
  );
}
