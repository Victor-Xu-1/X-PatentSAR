import { useEffect, useId, useRef } from 'react';
import { X } from 'lucide-react';
import type { ReactNode } from 'react';

function focusInitialControl(dialog: HTMLDialogElement) {
  const control = dialog.querySelector<HTMLElement>('[data-initial-focus]');
  if (!control || control.matches(':disabled') || control.closest('[hidden], [inert]'))
    return false;
  control.focus();
  return document.activeElement === control;
}

function awaitInitialControl(dialog: HTMLDialogElement) {
  if (focusInitialControl(dialog)) return () => {};
  const initialFocus = document.activeElement;
  const intents = ['focusin', 'pointerdown', 'keydown'] as const;
  const observer = new MutationObserver(() => {
    if (document.activeElement !== initialFocus || focusInitialControl(dialog)) stop();
  });
  function stop() {
    observer.disconnect();
    for (const event of intents) dialog.removeEventListener(event, stop);
  }
  for (const event of intents) dialog.addEventListener(event, stop);
  // The correction form arrives after the modal's loading state. Observe only
  // until its initial control is usable, or the user chooses where to interact.
  observer.observe(dialog, {
    childList: true,
    subtree: true,
    attributes: true,
    attributeFilter: ['data-initial-focus', 'disabled', 'hidden', 'inert', 'tabindex'],
  });
  return stop;
}

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
    if (!dialog) return;
    const previous = document.activeElement;
    const scope = previous?.closest('[data-dialog-focus-scope]');
    const focusKey = previous instanceof HTMLElement ? previous.dataset.focusKey : undefined;
    dialog.showModal();
    const stopInitialFocus = awaitInitialControl(dialog);
    return () => {
      stopInitialFocus();
      dialog.close();
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
        event.stopPropagation();
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
