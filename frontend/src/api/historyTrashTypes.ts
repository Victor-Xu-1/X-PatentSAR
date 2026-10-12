import type { HistoryKind } from './historyTypes';

export interface TrashPlan {
  revision: string;
  total: number;
  counts: Record<HistoryKind, number>;
  blocked: number;
  files_total: number;
  bytes_total: number;
  retained_targets: number;
  pending: TrashClearReceipt | null;
}
export interface TrashClearRequest {
  request_id: string;
  expected_revision: string;
  expected_total: number;
}
export interface TrashClearReceipt {
  request_id: string;
  plan_revision: string;
  cleared: number;
  counts: Record<HistoryKind, number>;
  started_at: string;
  completed_at: string | null;
  files_deleted: number;
  status: 'complete' | 'cleanup_pending';
  files_total: number;
  files_retained: number;
  bytes_removed: number;
  retained_targets: number;
}
