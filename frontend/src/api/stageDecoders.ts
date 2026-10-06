import type { CoreStageName, StageName, StageProgress } from './types';
import { stageNames } from './types';
import {
  array,
  boolean,
  ContractError,
  count,
  nullable,
  number,
  object,
  oneOf,
} from './validation';
import type { Decoder } from './validation';

const nonnegative: Decoder<number> = (input, path = '$') => {
  const value = number(input, path);
  if (value < 0) throw new ContractError(path);
  return value;
};
const measurement: Decoder<number> = (input, path = '$') => {
  const value = nonnegative(input, path);
  if (value > Number.MAX_SAFE_INTEGER) throw new ContractError(path);
  return value;
};
const resourceWait = object({
  reason: oneOf(['memory']),
  required_mb: measurement,
  available_mb: measurement,
  waited_seconds: measurement,
});
const progressShape = object({
  completed: count,
  total: count,
  cache_hits: count,
  failures: count,
  device: nullable(oneOf(['cpu', 'gpu'])),
  peak_rss_mb: nullable(nonnegative),
});
const progress: Decoder<StageProgress> = (input, path = '$') => {
  const value = progressShape(input, path);
  if (
    value.completed > value.total ||
    value.cache_hits > value.completed ||
    value.failures > value.completed
  )
    throw new ContractError(path);
  const fields = input as Record<string, unknown>;
  if (!Object.hasOwn(fields, 'phase')) return value;
  return {
    ...value,
    phase: nullable(oneOf(['recognition', 'properties']))(fields.phase, `${path}.phase`),
  };
};

function stageDecoder<const T extends readonly StageName[]>(names: T) {
  const shape = object({
    name: oneOf(names),
    status: oneOf(['pending', 'running', 'ok', 'empty', 'failed', 'warnings']),
    count: nullable(count),
    duration_seconds: nullable(nonnegative),
    progress: nullable(progress),
    reused_checkpoint: nullable(boolean),
  });
  return (input: unknown, path = '$') => {
    const stage = shape(input, path);
    const fields = input as Record<string, unknown>;
    const skipped = Object.hasOwn(fields, 'skipped')
      ? count(fields.skipped, `${path}.skipped`)
      : undefined;
    if (skipped !== undefined && skipped > 1_000_000) throw new ContractError(`${path}.skipped`);
    return {
      ...stage,
      ...(skipped === undefined ? {} : { skipped }),
      ...(Object.hasOwn(fields, 'resource_wait')
        ? { resource_wait: nullable(resourceWait)(fields.resource_wait, `${path}.resource_wait`) }
        : {}),
    };
  };
}
export const decodeCoreStage = stageDecoder(stageNames);
export const decodeAdmetStage = stageDecoder(['admet']);
export const decodeStageOrder: Decoder<CoreStageName[]> = (input, path = '$') => {
  if (!Array.isArray(input) || input.length > stageNames.length) throw new ContractError(path);
  const names = array(oneOf(stageNames))(input, path);
  if (
    names.length !== 0 &&
    (names.length !== stageNames.length || new Set(names).size !== stageNames.length)
  )
    throw new ContractError(path);
  return names;
};
