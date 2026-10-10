import type { Dataset, Molecule } from '../../api/sarTypes';
import { SourceLinks } from './SourceLinks';
import { useTranslation } from '../../i18n';
export function MoleculeEvidence({
  dataset,
  molecule,
  includeLinks = true,
  includeIssues = true,
}: {
  dataset: Dataset;
  molecule: Molecule;
  includeLinks?: boolean;
  includeIssues?: boolean;
}) {
  const { t } = useTranslation();
  return (
    <div className="sar-evidence">
      <strong>{molecule.label}</strong>
      <p className="sar-chemistry">{molecule.smiles ?? '—'}</p>
      {includeLinks && <SourceLinks dataset={dataset} molecule={molecule} />}
      <ul>
        {molecule.observations.map((observation, index) => (
          <li key={index}>
            <span>
              {dataset.metrics.find((metric) => metric.id === observation.metric_id)?.name ??
                observation.metric_id}
              : {observation.value}
            </span>
            {observation.unit !== null && <span> · {observation.unit}</span>}
            <dl>
              <div>
                <dt>source_page</dt>
                <dd>{observation.source_page ?? '—'}</dd>
              </div>
              {Object.entries(observation.context).map(([key, value]) => (
                <div key={key}>
                  <dt>{key}</dt>
                  <dd>{value ?? '—'}</dd>
                </div>
              ))}
              <div>
                <dt>source_kind</dt>
                <dd>{observation.source_kind}</dd>
              </div>
              <div>
                <dt>source_row</dt>
                <dd>{observation.source_row ?? '—'}</dd>
              </div>
            </dl>
          </li>
        ))}
      </ul>
      {includeIssues && !!molecule.issues.length && (
        <ul>
          {molecule.issues.map((issue, i) => (
            <li key={i}>{issue}</li>
          ))}
        </ul>
      )}
      {molecule.properties && (
        <details>
          <summary>{t('性质')}</summary>
          <dl>
            {Object.entries(molecule.properties).map(([key, value]) => (
              <div key={key}>
                <dt>{key}</dt>
                <dd>
                  {value ?? '—'} · {molecule.property_origins?.[key] ?? 'not_provided'}
                </dd>
              </div>
            ))}
          </dl>
        </details>
      )}
      {molecule.predictions && (
        <details>
          <summary>
            {t('已捕获的预测')} · {molecule.prediction_origin ?? 'not_provided'}
          </summary>
          <dl>
            {Object.entries(molecule.predictions).map(([key, value]) => (
              <div key={key}>
                <dt>{key}</dt>
                <dd>{value ?? '—'}</dd>
              </div>
            ))}
          </dl>
        </details>
      )}
    </div>
  );
}
