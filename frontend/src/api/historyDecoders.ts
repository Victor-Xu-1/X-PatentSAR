import {
  boolean,
  ContractError,
  count,
  nullable,
  object,
  oneOf,
  positive,
  string,
} from './validation';
import type { Decoder } from './validation';
import { historyKinds } from './historyTypes';
import type { HistoryEntry, HistoryKind, HistoryList } from './historyTypes';

export const decodeHistoryKind = oneOf(historyKinds);
export const decodeHistoryId: Decoder<string> = (value, path = '$.id') => {
  const id = string(value, path);
  if (!/^(?:[a-f0-9]{32}|[a-f0-9]{64})$/.test(id)) throw new ContractError(path);
  return id;
};
export const decodeHistoryProjectId: Decoder<string> = (value, path = '$.project_id') => {
  const id = decodeHistoryId(value, path);
  if (id.length !== 32) throw new ContractError(path);
  return id;
};
export function decodeHistoryIdentity(kind: HistoryKind, value: unknown, path = '$.id'): string {
  const id = decodeHistoryId(value, path);
  if (id.length !== (kind === 'export' ? 64 : 32)) throw new ContractError(path);
  return id;
}
export const decodeHistoryRevision: Decoder<string> = (value, path = '$.revision') => {
  const revision = string(value, path);
  if (!/^[a-f0-9]{64}$/.test(revision)) throw new ContractError(path);
  return revision;
};
function text(min: number, max: number): Decoder<string> {
  return (value, path = '$') => {
    const result = string(value, path);
    const length = Array.from(result).length;
    const hasControl = Array.from(result).some((character) => {
      const code = character.charCodeAt(0);
      return code < 32 && ![9, 10, 13].includes(code);
    });
    if (length < min || length > max || hasControl) throw new ContractError(path);
    return result;
  };
}
const entryShape = object({
  kind: decodeHistoryKind,
  id: decodeHistoryId,
  project_id: nullable(decodeHistoryProjectId),
  title: text(1, 250),
  status: text(0, 40),
  created_at: text(0, 80),
  deleted_at: nullable(text(0, 80)),
  revision: decodeHistoryRevision,
  can_delete: boolean,
  can_restore: boolean,
  blocked_reason: nullable(text(0, 300)),
  size_bytes: nullable(count),
});
export const decodeHistoryEntry: Decoder<HistoryEntry> = (value, path = '$') => {
  const entry = entryShape(value, path);
  decodeHistoryIdentity(entry.kind, entry.id, `${path}.id`);
  if (
    (entry.deleted_at === null && entry.can_restore) ||
    (entry.deleted_at !== null && entry.can_delete) ||
    (entry.blocked_reason !== null && entry.can_restore) ||
    (entry.kind === 'environment_operation' && entry.project_id !== null) ||
    (entry.kind === 'project' && entry.project_id !== entry.id)
  )
    throw new ContractError(`${path}.history_state`);
  return entry;
};
export const decodeHistoryPageSize: Decoder<number> = (value, path = '$.page_size') => {
  const size = positive(value, path);
  if (size > 100) throw new ContractError(path);
  return size;
};
const listShape = object({
  items: (value: unknown, path = '$.items') => {
    if (!Array.isArray(value) || value.length > 100) throw new ContractError(path);
    return value.map((entry, index) => decodeHistoryEntry(entry, `${path}[${index}]`));
  },
  total: count,
  page: positive,
  page_size: decodeHistoryPageSize,
});
export const decodeHistoryList: Decoder<HistoryList> = (value, path = '$') => {
  const list = listShape(value, path);
  if (
    list.items.length > list.page_size ||
    list.items.length > list.total ||
    new Set(list.items.map((entry) => `${entry.kind}:${entry.id}`)).size !== list.items.length
  )
    throw new ContractError(path);
  return list;
};
