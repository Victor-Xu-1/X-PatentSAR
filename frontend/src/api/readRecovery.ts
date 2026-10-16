import { ApiError } from './errors';

const delays = [1000, 3000, 7000] as const;

/** Only audited GET observers opt in; transport/authentication owns its own limits. */
export function readRecoveryDelay(error: unknown, consecutiveFailures: number): number | null {
  if (!(error instanceof ApiError) || error.uncertain) return null;
  const transient =
    (error.status === 0 && ['network_error', 'timeout'].includes(error.code)) ||
    [502, 503, 504].includes(error.status);
  return transient ? (delays[consecutiveFailures - 1] ?? null) : null;
}
