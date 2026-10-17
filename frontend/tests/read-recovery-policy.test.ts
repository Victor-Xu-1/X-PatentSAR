import { expect, it } from 'vitest';
import { ApiError } from '../src/api/errors';
import { ContractError } from '../src/api/validation';
import { readRecoveryDelay } from '../src/api/readRecovery';

it.each([
  new ApiError(0, 'network_error', 'Network fault'),
  new ApiError(0, 'timeout', 'Read timeout'),
  new ApiError(502, 'http_error', 'Gateway unavailable'),
  new ApiError(503, 'http_error', 'Service unavailable'),
  new ApiError(504, 'http_error', 'Gateway timeout'),
])('bounds transient GET recovery for $code / $status', (fault) => {
  expect([1, 2, 3, 4, 5].map((attempt) => readRecoveryDelay(fault, attempt))).toEqual([
    1000,
    3000,
    7000,
    null,
    null,
  ]);
});

it.each([
  new Error('Unknown failure'),
  new ContractError('$.job'),
  new ApiError(401, 'session_required', 'Session fault'),
  new ApiError(403, 'forbidden', 'Permission fault'),
  new ApiError(404, 'missing', 'Missing task'),
  new ApiError(409, 'conflict', 'Identity conflict'),
  new ApiError(422, 'invalid', 'Invalid input'),
  new ApiError(429, 'rate_limit', 'Rate limit requires explicit response handling'),
  new ApiError(500, 'unexpected', 'Unclassified server fault'),
  new ApiError(0, 'invalid_json', 'Invalid data'),
  new ApiError(0, 'sar_transport', 'Byte/upload adapter not opted in'),
  new ApiError(0, 'network_error', 'Unknown write outcome', true),
  new ApiError(503, 'http_error', 'Unknown write outcome', true),
])('does not turn $name / $code into a retryable read', (fault) => {
  expect(readRecoveryDelay(fault, 1)).toBeNull();
});

it.each([0, -1, 1.5, NaN, Infinity])('rejects invalid failure counter %s', (counter) => {
  expect(readRecoveryDelay(new ApiError(503, 'http_error', 'Unavailable'), counter)).toBeNull();
});
