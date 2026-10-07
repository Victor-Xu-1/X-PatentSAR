import type { ApiClient } from './client';
import type { HistoryAction, HistoryKind, HistoryQuery } from './historyTypes';
import { boolean, ContractError, positive } from './validation';
import {
  decodeHistoryEntry,
  decodeHistoryIdentity,
  decodeHistoryKind,
  decodeHistoryList,
  decodeHistoryPageSize,
  decodeHistoryProjectId,
  decodeHistoryRevision,
} from './historyDecoders';

export function historyApi(client: ApiClient) {
  const entryPath = (kind: HistoryKind, id: string) =>
    `/history/${decodeHistoryKind(kind)}/${encodeURIComponent(decodeHistoryIdentity(kind, id))}`;
  const scoped = (kind: HistoryKind, id: string, action?: HistoryAction) => (value: unknown) => {
    const entry = decodeHistoryEntry(value);
    if (
      entry.kind !== kind ||
      entry.id !== id ||
      (action === 'delete' && entry.deleted_at === null) ||
      (action === 'restore' && entry.deleted_at !== null)
    )
      throw new ContractError('$.history_entry');
    return entry;
  };
  const mutate = (kind: HistoryKind, id: string, revision: string, action: HistoryAction) =>
    client.mutate(
      `${entryPath(kind, id)}/${action}`,
      'POST',
      { expected_revision: decodeHistoryRevision(revision) },
      scoped(kind, id, action),
    );
  return {
    history: (query: HistoryQuery, signal: AbortSignal) => {
      const kind = decodeHistoryKind(query.kind);
      const deleted = boolean(query.deleted ?? false);
      const page = positive(query.page ?? 1);
      const pageSize = decodeHistoryPageSize(query.page_size ?? 50);
      const projectId =
        query.project_id === undefined ? undefined : decodeHistoryProjectId(query.project_id);
      if (kind === 'environment_operation' && projectId !== undefined)
        throw new ContractError('$.project_id');
      const params = new URLSearchParams({
        kind,
        deleted: String(deleted),
        page: String(page),
        page_size: String(pageSize),
      });
      if (projectId !== undefined) params.set('project_id', projectId);
      return client.get(
        `/history?${params}`,
        (value) => {
          const list = decodeHistoryList(value);
          if (
            list.page !== page ||
            list.page_size !== pageSize ||
            list.items.some(
              (entry) =>
                entry.kind !== kind ||
                (entry.deleted_at !== null) !== deleted ||
                (projectId !== undefined && entry.project_id !== projectId),
            )
          )
            throw new ContractError('$.history_list');
          return list;
        },
        signal,
      );
    },
    historyEntry: (kind: HistoryKind, id: string, signal: AbortSignal) =>
      client.get(entryPath(kind, id), scoped(kind, id), signal),
    deleteHistory: (kind: HistoryKind, id: string, revision: string) =>
      mutate(kind, id, revision, 'delete'),
    restoreHistory: (kind: HistoryKind, id: string, revision: string) =>
      mutate(kind, id, revision, 'restore'),
  };
}
