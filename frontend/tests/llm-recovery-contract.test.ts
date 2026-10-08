import { describe, expect, it } from 'vitest';
import { decodeJob } from '../src/api/decoders';
import { decodeLLMTestResult } from '../src/api/llmDecoders';
import { ContractError } from '../src/api/validation';
import { job } from './fixtures';

const recovery = {
  status: 'blocked',
  reason: 'authentication_failed',
  remaining_calls: 3,
  retry_after_seconds: null,
  can_reauthorize: true,
};
const stage = job.stages[0]!;

describe('additive API-v1 LLM recovery facts', () => {
  it('keeps absent recovery and repair unknown for old DTOs', () => {
    const decoded = decodeJob(job);
    expect(Object.hasOwn(decoded, 'llm_recovery')).toBe(false);
    expect(Object.hasOwn(decoded.stages[0]!, 'repair')).toBe(false);
  });

  it.each(['disabled', 'ready', 'blocked', 'cooldown', 'exhausted', 'unavailable'])(
    'preserves the supplied %s state and actual zero/boundary/null facts',
    (status) => {
      for (const remaining_calls of [null, 0, 8]) {
        for (const retry_after_seconds of [null, 0, 45]) {
          const fact = { ...recovery, status, remaining_calls, retry_after_seconds };
          expect(decodeJob({ ...job, llm_recovery: fact }).llm_recovery).toEqual(fact);
        }
      }
    },
  );

  it.each([
    null,
    undefined,
    [],
    { ...recovery, status: 'unknown' },
    { ...recovery, reason: undefined },
    { ...recovery, reason: 123 },
    { ...recovery, remaining_calls: undefined },
    { ...recovery, remaining_calls: -1 },
    { ...recovery, remaining_calls: 9 },
    { ...recovery, remaining_calls: 0.5 },
    { ...recovery, remaining_calls: '3' },
    { ...recovery, retry_after_seconds: undefined },
    { ...recovery, retry_after_seconds: -1 },
    { ...recovery, retry_after_seconds: 46 },
    { ...recovery, retry_after_seconds: Infinity },
    { ...recovery, retry_after_seconds: NaN },
    { ...recovery, can_reauthorize: undefined },
    { ...recovery, can_reauthorize: 'true' },
    { ...recovery, api_key: 'synthetic-not-a-credential' },
  ])('fails closed on malformed recovery %#', (llm_recovery) => {
    expect(() => decodeJob({ ...job, llm_recovery })).toThrow(ContractError);
  });

  it('preserves nullable reason and finite bounded retry duration without inventing a countdown', () => {
    const fact = { ...recovery, reason: null, retry_after_seconds: 0.5 };
    expect(decodeJob({ ...job, llm_recovery: fact }).llm_recovery).toEqual(fact);
  });

  it.each([
    { regions: 0, unresolved: 0 },
    { regions: 25000, unresolved: 25000 },
    { regions: 7, unresolved: 2 },
  ])('preserves actual repair counters %#', (repair) => {
    expect(decodeJob({ ...job, stages: [{ ...stage, repair }] }).stages[0]?.repair).toEqual(repair);
  });

  it.each([
    null,
    undefined,
    [],
    {},
    { regions: 3 },
    { unresolved: 1 },
    { regions: -1, unresolved: 0 },
    { regions: 25001, unresolved: 0 },
    { regions: 3, unresolved: 4 },
    { regions: 3, unresolved: -1 },
    { regions: 3, unresolved: 25001 },
    { regions: 3.5, unresolved: 1 },
    { regions: 3, unresolved: 0.5 },
    { regions: '3', unresolved: 1 },
    { regions: 3, unresolved: Infinity },
    { regions: 3, unresolved: 1, accepted: true },
  ])('rejects missing, unsafe and contradictory repair facts %#', (repair) => {
    expect(() => decodeJob({ ...job, stages: [{ ...stage, repair }] })).toThrow(ContractError);
  });

  it('uses the same repair boundary for the existing research stage', () => {
    const admet_stage = { ...stage, name: 'admet', repair: { regions: 5, unresolved: 2 } };
    expect(decodeJob({ ...job, include_admet: true, admet_stage }).admet_stage?.repair).toEqual(
      admet_stage.repair,
    );
    expect(() =>
      decodeJob({
        ...job,
        include_admet: true,
        admet_stage: { ...admet_stage, repair: { regions: 1, unresolved: 2 } },
      }),
    ).toThrow(ContractError);
  });
});

describe('credential-free synthetic LLM test reasons', () => {
  it.each([
    'nonce_verified',
    'invalid_response',
    'transport_unavailable',
    'settings_changed',
    'input_budget',
    'authentication_failed',
    'rate_limited',
    'provider_unavailable',
    'timeout',
    'cancelled',
    'cache_unavailable',
    'unsafe_cache',
  ])('preserves old and newly approved reason %s', (reason) => {
    const result = {
      status: reason === 'nonce_verified' ? 'passed' : 'failed',
      reason,
      settings_revision: 4,
      checked_at: '2026-10-08T00:00:00Z',
    };
    expect(decodeLLMTestResult(result)).toEqual(result);
  });
});
