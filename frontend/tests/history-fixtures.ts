import type { HistoryEntry, HistoryList } from '../src/api/historyTypes';
import { job, project } from './fixtures';

export const historyProject = { ...project, id: '1'.repeat(32) };
export const historyJob = { ...job, id: '2'.repeat(32), project_id: historyProject.id };
const ids = {
  project: historyProject.id,
  job: historyJob.id,
  export: 'a'.repeat(64),
  environment_operation: '3'.repeat(32),
};

// Synthetic DTOs only; never imported by application source or used as runtime fallbacks.
export function historyEntry(overrides: Partial<HistoryEntry> = {}): HistoryEntry {
  return {
    kind: 'project',
    id: ids[overrides.kind ?? 'project'],
    project_id: overrides.kind === 'environment_operation' ? null : historyProject.id,
    title: project.title,
    status: 'not_run',
    created_at: project.created_at,
    deleted_at: null,
    revision: 'a'.repeat(64),
    can_delete: true,
    can_restore: false,
    blocked_reason: null,
    size_bytes: null,
    ...overrides,
  };
}
export function historyList(
  items: HistoryEntry[],
  overrides: Partial<HistoryList> = {},
): HistoryList {
  return { items, total: items.length, page: 1, page_size: 50, ...overrides };
}
export function trashed(entry: HistoryEntry): HistoryEntry {
  return {
    ...entry,
    deleted_at: '2026-10-08T00:00:00Z',
    revision: 'b'.repeat(64),
    can_delete: false,
    can_restore: true,
  };
}
