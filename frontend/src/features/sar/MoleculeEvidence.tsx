import type { Dataset, Molecule } from '../../api/sarTypes';
import { SourceLinks } from './SourceLinks';
export function MoleculeEvidence({
  dataset,
  molecule,
  includeLinks = true,
}: {
  dataset: Dataset;
  molecule: Molecule;
  includeLinks?: boolean;
}) {
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
      {!!molecule.issues.length && (
        <ul>
          {molecule.issues.map((issue, i) => (
            <li key={i}>{issue}</li>
          ))}
        </ul>
      )}
    </div>
  );
}
