import { useEffect, useId, useRef } from 'react';
import { X } from 'lucide-react';
import type { ReactNode } from 'react';

export function Dialog({
  title,
  children,
  onClose,
  busy = false,
  wide = false,
  className = '',
}: {
  title: string;
  children: ReactNode;
  onClose: () => void;
  busy?: boolean;
  wide?: boolean;
  className?: string;
}) {
  const ref = useRef<HTMLDialogElement>(null);
  const titleId = useId();
  useEffect(() => {
    const dialog = ref.current;
    const previous = document.activeElement;
    const scope = previous?.closest('[data-dialog-focus-scope]');
    const focusKey = previous instanceof HTMLElement ? previous.dataset.focusKey : undefined;
    dialog?.showModal();
    dialog?.querySelector<HTMLElement>('[data-initial-focus]')?.focus();
    return () => {
      dialog?.close();
      if (previous instanceof HTMLElement && previous.isConnected) {
        previous.focus();
      } else if (scope?.isConnected) {
        // A debounced query can replace the opener while the modal is active.
        // Restore its logical identity within this workspace, never another view.
        const replacement = focusKey
          ? Array.from(scope.querySelectorAll<HTMLElement>('[data-focus-key]')).find(
              (element) => element.dataset.focusKey === focusKey,
            )
          : undefined;
        (replacement ?? scope.querySelector<HTMLElement>('[data-dialog-focus-fallback]'))?.focus();
      }
    };
  }, []);
  return (
    <dialog
      ref={ref}
      className={`dialog${wide ? ' dialog-wide' : ''}${className ? ` ${className}` : ''}`}
      aria-labelledby={titleId}
      onCancel={(event) => {
        event.preventDefault();
        if (!busy) onClose();
      }}
    >
      <header className="dialog-header">
        <h2 id={titleId}>{title}</h2>
        <button
          type="button"
          className="icon-button"
          aria-label="关闭对话框"
          onClick={onClose}
          disabled={busy}
        >
          <X size={20} />
        </button>
      </header>
      {children}
    </dialog>
  );
}
