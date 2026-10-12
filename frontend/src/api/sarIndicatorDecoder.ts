/** Read-only setup conventions, never added to captured study contexts/reports. */
import { ContractError, object, oneOf, string } from './validation';
import { additions, recordOf } from './sarDecoders';
import type { StudyContext } from './sarStudyTypes';

const indicator = object({ direction: oneOf(['lower', 'higher', 'unknown']), rule: string });
export function indicatorDefaults(value: unknown, contexts: StudyContext[], path: string) {
  const result = additions(
    value,
    {
      policy_defaults: recordOf(indicator, 1000),
      metric_defaults: recordOf(indicator, 1000),
    },
    path,
  );
  const contextIds = new Set(contexts.map((c) => c.id));
  const metricIds = new Set(contexts.map((c) => c.metric_id));
  if (
    Object.keys(result.policy_defaults ?? {}).some((id) => !contextIds.has(id)) ||
    Object.keys(result.metric_defaults ?? {}).some((id) => !metricIds.has(id))
  )
    throw new ContractError(path + '.indicator_defaults');
  return result;
}
