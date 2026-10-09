import type { StudyReport, StudyBin } from './sarStudyTypes';
import { ContractError } from './validation';

/** Legacy reports remain readable; only the current contract promises a partition. */
export function verifyStudyConservation(report: StudyReport, path: string) {
  if (report.counting_contract !== 'unique-molecules-v2') return;
  const require = (valid: boolean) => {
    if (!valid) throw new ContractError(path + '.conservation');
  };
  // Overview intentionally omits the paginated row payload. The complete
  // descriptive scaffold partition still carries every immutable source ID.
  const population = report.scaffolds
    .filter((group) => group.assignment_kind === 'murcko')
    .flatMap((group) => group.molecule_ids);
  const ids = new Set(population);
  const policies = report.policies.map((policy) => policy.context_id);
  const keys = (bins: StudyBin[]) => bins.map((bin) => JSON.stringify([bin.kind, bin.label]));
  require(ids.size === report.molecule_count && population.length === report.molecule_count);
  if (report.rows.length) {
    require(
      report.rows.length === report.molecule_count &&
        new Set(report.rows.map((row) => row.molecule_id)).size === ids.size,
    );
    require(report.rows.every((row) => ids.has(row.molecule_id)));
    require(report.rows.filter((row) => row.eligible).length === report.eligible_count);
  }
  require(
    report.contexts.reduce((sum, context) => sum + context.observation_count, 0) ===
      report.observation_count,
  );
  require(
    JSON.stringify(report.distributions.map((item) => item.context_id)) ===
      JSON.stringify(policies),
  );
  const primaryDomain = new Set(keys(report.distributions[0]?.bins ?? []));
  const binsValid = (bins: StudyBin[], members: string[]) => {
    require(new Set(members).size === members.length && members.every((id) => ids.has(id)));
    require(bins.reduce((sum, bin) => sum + bin.molecules, 0) === members.length);
    require(
      new Set(keys(bins)).size === bins.length && keys(bins).every((key) => primaryDomain.has(key)),
    );
  };
  for (const distribution of report.distributions) {
    const context = report.contexts.find((item) => item.id === distribution.context_id);
    require(
      distribution.observed_molecules + distribution.missing_molecules === report.molecule_count,
    );
    require(
      distribution.bins.reduce((sum, bin) => sum + bin.molecules, 0) === report.molecule_count,
    );
    require(
      distribution.bins.reduce((sum, bin) => sum + bin.observations, 0) ===
        distribution.observations,
    );
    require(distribution.observations === context?.observation_count);
    require(
      distribution.missing_molecules ===
        distribution.bins
          .filter((bin) => bin.kind === 'missing')
          .reduce((sum, bin) => sum + bin.molecules, 0),
    );
    require(distribution.unresolved_molecules <= distribution.observed_molecules);
    require(new Set(keys(distribution.bins)).size === distribution.bins.length);
  }
  const members: string[] = [];
  for (const scaffold of report.scaffolds) {
    binsValid(scaffold.bins, scaffold.molecule_ids);
    require(scaffold.molecule_count === scaffold.molecule_ids.length);
    if (scaffold.assignment_kind === 'murcko') members.push(...scaffold.molecule_ids);
  }
  require(members.length === ids.size && new Set(members).size === ids.size);
  for (const summary of report.regions) {
    const fragmentMembers: string[] = [];
    require(
      summary.matched + summary.not_matched + summary.ambiguous + summary.ineligible ===
        report.molecule_count - 1,
    );
    for (const fragment of summary.fragments) {
      binsValid(fragment.bins, fragment.molecule_ids);
      require(fragment.molecule_count === fragment.molecule_ids.length);
      fragmentMembers.push(...fragment.molecule_ids);
    }
    require(
      new Set(fragmentMembers).size === fragmentMembers.length &&
        fragmentMembers.length === summary.matched + 1,
    );
  }
  const candidates = new Set(report.candidates.map((row) => row.molecule_id));
  const selected = report.rows.filter((row) => row.candidate_status === 'selected');
  require(
    candidates.size === report.candidates.length && [...candidates].every((id) => ids.has(id)),
  );
  if (report.rows.length) {
    require(
      selected.length === candidates.size &&
        selected.every((row) => candidates.has(row.molecule_id)),
    );
    require(
      report.candidates.every(
        (candidate) =>
          JSON.stringify(candidate) ===
          JSON.stringify(report.rows.find((row) => row.molecule_id === candidate.molecule_id)),
      ),
    );
  }
  const declarations = report.context_declarations ?? [];
  require(new Set(declarations.map((claim) => claim.context_id)).size === declarations.length);
  require(declarations.every((claim) => policies.includes(claim.context_id)));
}
