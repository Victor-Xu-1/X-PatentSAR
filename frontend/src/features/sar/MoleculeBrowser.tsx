import { useCallback, useState } from 'react';
import { sarApi } from '../../api/sarApi';
import type { Dataset, Molecule } from '../../api/sarTypes';
import { useSARResource } from './useSARResource';
import { useDebounced } from '../../hooks/useDebounced';
import { Empty, Loading } from '../../components/Feedback';
import { SARFailure } from './SARFailure';
import { useTranslation } from '../../i18n';
import { PageControls } from './PageControls';
import { MoleculeEvidence } from './MoleculeEvidence';
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
  const resource = useSARResource(
    `sar:rows:${dataset.id}:${dataset.revision}:${page}:${search}`,
    active,
    load,
  );
  return (
    <section className="sar-panel sar-reference-browser" aria-label={t('选择参考分子')}>
      <h2>{t('选择参考分子')}</h2>
      <label>
        {t('搜索编号或 SMILES')}
        <input
          type="search"
          maxLength={200}
          disabled={!active}
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
                    <th>{t('参考')}</th>
                    <th>{t('原始活性')}</th>
                    <th>{t('来源详情')}</th>
                  </tr>
                </thead>
                <tbody>
                  {resource.data.items.map((molecule) => (
                    <tr key={molecule.id} data-selected={referenceId === molecule.id}>
                      <th scope="row">{molecule.label}</th>
                      <td>
                        <button
                          type="button"
                          disabled={
                            !active ||
                            !resource.validated ||
                            query !== search ||
                            dataset.stale ||
                            !molecule.eligible ||
                            !molecule.graph_sha256
                          }
                          aria-pressed={referenceId === molecule.id}
                          onClick={() => onReference(molecule)}
                        >
                          {t('参考')}
                        </button>
                        {!molecule.eligible && <small>{t('不可分析')}</small>}
                      </td>
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
                        {!molecule.smiles && <small>{t('未提供 SMILES')}</small>}
                        {!!molecule.issues.length && (
                          <ul>
                            {molecule.issues.map((issue, i) => (
                              <li key={i}>{issue}</li>
                            ))}
                          </ul>
                        )}
                        <details>
                          <summary>{t('来源详情')}</summary>
                          <MoleculeEvidence
                            dataset={dataset}
                            molecule={molecule}
                            includeIssues={false}
                          />
                        </details>
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
            disabled={!active || !resource.validated || query !== search}
          />
        </>
      )}
    </section>
  );
}
