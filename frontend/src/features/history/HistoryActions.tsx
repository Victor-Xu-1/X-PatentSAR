import { useTranslation } from '../../i18n';
import { useState } from 'react';
import { RotateCcw, Trash2 } from 'lucide-react';
import type { HistoryAction, HistoryEntry, HistoryTarget } from '../../api/historyTypes';
import { DeletionDialog } from './DeletionDialog';

export function HistoryActions({
  target,
  onChanged,
  action = 'delete',
  iconOnly = false,
}: {
  target: HistoryTarget;
  onChanged: (entry: HistoryEntry) => void;
  action?: HistoryAction;
  iconOnly?: boolean;
}) {
  const { t } = useTranslation();
  const [open, setOpen] = useState(false);
  const label = t(action === 'restore' ? '恢复 {title}' : '删除 {title}', { title: target.title });
  return (
    <>
      <button
        type="button"
        className={`history-action${iconOnly ? ' icon-button' : ''}`}
        aria-label={label}
        title={label}
        onClick={() => setOpen(true)}
      >
        {action === 'restore' ? (
          <RotateCcw size={15} aria-hidden="true" />
        ) : (
          <Trash2 size={15} aria-hidden="true" />
        )}
        {!iconOnly && <span>{action === 'restore' ? t('恢复') : t('删除')}</span>}
      </button>
      {open && (
        <DeletionDialog
          key={`${target.kind}:${target.id}:${action}`}
          target={target}
          action={action}
          onClose={() => setOpen(false)}
          onChanged={onChanged}
        />
      )}
    </>
  );
}
