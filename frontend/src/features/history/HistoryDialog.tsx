import { useCallback, useState } from 'react';
import { api } from '../../api';
import { historyKinds } from '../../api/historyTypes';
import type { HistoryEntry, HistoryKind } from '../../api/historyTypes';
import { Dialog } from '../../components/Dialog';
import { Empty, ErrorNotice, Loading } from '../../components/Feedback';
import { useResource } from '../../hooks/useResource';
import { dateText } from '../../model/presentation';
import { HistoryActions } from './HistoryActions';
import { historyLabels, retentionNotice } from './historyPresentation';

export function HistoryDialog({
  title,
  initialKind,
  deleted = false,
  projectId,
  filters = false,
  onClose,
  onChanged,
  onTrash,
}: {
  title: string;
  initialKind: HistoryKind;
  deleted?: boolean;
  projectId?: string;
  filters?: boolean;
  onClose: () => void;
  onChanged: (entry: HistoryEntry) => void;
  onTrash?: () => void;
}) {
  const [kind, setKind] = useState(initialKind);
  const [page, setPage] = useState(1);
  const [pageSize, setPageSize] = useState(50);
  const load = useCallback(
    (signal: AbortSignal) =>
      api.history(
        {
          kind,
          deleted,
          page,
          page_size: pageSize,
          ...(projectId === undefined ? {} : { project_id: projectId }),
        },
        signal,
      ),
    [kind, deleted, page, pageSize, projectId],
  );
  const resource = useResource(
    `history:${kind}:${projectId ?? 'all'}:${deleted}:${page}:${pageSize}`,
    load,
  );
  function changed(entry: HistoryEntry) {
    onChanged(entry);
    // Return to a valid first page after removal, including the last item on the last page.
    setPage(1);
    resource.reload();
  }
  const data = resource.data;
  return (
    <Dialog title={title} onClose={onClose} className="history-dialog">
      <div className="dialog-body" data-dialog-focus-scope aria-busy={resource.loading}>
        <div className="inline-actions history-controls">
          {filters && (
            <label className="form-field">
              记录类型
              <select
                data-initial-focus
                aria-label="回收站记录类型"
                value={kind}
                onChange={(event) => {
                  setKind(event.target.value as HistoryKind);
                  setPage(1);
                }}
              >
                {historyKinds.map((value) => (
                  <option key={value} value={value}>
                    {historyLabels[value]}
                  </option>
                ))}
              </select>
            </label>
          )}
          <button
            type="button"
            data-dialog-focus-fallback
            disabled={resource.loading}
            onClick={resource.reload}
          >
            刷新记录
          </button>
          {onTrash && (
            <button type="button" onClick={onTrash}>
              回收站
            </button>
          )}
        </div>
        <p className="muted">{retentionNotice}</p>
        {deleted && <p className="muted">先恢复项目，再恢复该项目下的任务或文件。</p>}
        {resource.error ? (
          <ErrorNotice error={resource.error} onRetry={resource.reload} />
        ) : resource.loading && !data ? (
          <Loading label="正在读取记录…" />
        ) : !data?.items.length ? (
          <Empty
            title="没有记录"
            description={deleted ? '此类型回收站为空。' : '暂无已保存记录。'}
          />
        ) : (
          <ul className="history-entries" aria-label={title}>
            {data.items.map((entry) => (
              <li key={`${entry.kind}:${entry.id}`}>
                <div className="history-entry-content">
                  <strong>{entry.title}</strong>
                  <time dateTime={entry.deleted_at ?? entry.created_at}>
                    {dateText(entry.deleted_at ?? entry.created_at)}
                  </time>
                </div>
                <HistoryActions
                  target={entry}
                  action={deleted ? 'restore' : 'delete'}
                  onChanged={changed}
                />
              </li>
            ))}
          </ul>
        )}
        <footer className="history-pagination" aria-label="历史记录分页">
          <span className="muted">
            共 {data?.total ?? 0} 条 · 第 {page} 页
          </span>
          <div className="inline-actions">
            <button
              type="button"
              aria-label="上一页历史记录"
              disabled={resource.loading || page <= 1}
              onClick={() => setPage((value) => value - 1)}
            >
              上一页
            </button>
            <button
              type="button"
              aria-label="下一页历史记录"
              disabled={
                resource.loading || !data || page >= Math.max(1, Math.ceil(data.total / pageSize))
              }
              onClick={() => setPage((value) => value + 1)}
            >
              下一页
            </button>
            <select
              aria-label="每页历史记录数量"
              value={pageSize}
              disabled={resource.loading}
              onChange={(event) => {
                setPageSize(Number(event.target.value));
                setPage(1);
              }}
            >
              {[25, 50, 100].map((size) => (
                <option key={size} value={size}>
                  {size} 条/页
                </option>
              ))}
            </select>
          </div>
        </footer>
        <footer className="dialog-actions">
          <button type="button" data-initial-focus={!filters || undefined} onClick={onClose}>
            关闭
          </button>
        </footer>
      </div>
    </Dialog>
  );
}
