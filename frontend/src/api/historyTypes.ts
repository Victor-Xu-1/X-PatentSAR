export const historyKinds = ['project', 'job', 'export', 'environment_operation'] as const;
export type HistoryKind = (typeof historyKinds)[number];
export type HistoryAction = 'delete' | 'restore';

export interface HistoryTarget {
  kind: HistoryKind;
  id: string;
  title: string;
}
export interface HistoryEntry extends HistoryTarget {
  project_id: string | null;
  status: string;
  created_at: string;
  deleted_at: string | null;
  revision: string;
  can_delete: boolean;
  can_restore: boolean;
  blocked_reason: string | null;
  size_bytes: number | null;
}
export interface HistoryList {
  items: HistoryEntry[];
  total: number;
  page: number;
  page_size: number;
}
export interface HistoryQuery {
  kind: HistoryKind;
  project_id?: string;
  deleted?: boolean;
  page?: number;
  page_size?: number;
}
