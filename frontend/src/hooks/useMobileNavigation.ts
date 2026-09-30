import { useEffect } from 'react';
import { useMediaQuery } from './useMediaQuery';

export function useMobileNavigation(open: boolean, onClose: () => void) {
  const narrow = useMediaQuery('(max-width: 760px)');
  useEffect(() => {
    if (!narrow || !open) return;
    const opener = document.querySelector<HTMLElement>('.menu-toggle');
    document.querySelector<HTMLElement>('#primary-sidebar .nav-item:not(:disabled)')?.focus();
    const escape = (event: KeyboardEvent) => {
      if (event.key === 'Escape') {
        event.preventDefault();
        onClose();
      }
    };
    document.addEventListener('keydown', escape);
    return () => {
      document.removeEventListener('keydown', escape);
      opener?.focus();
    };
  }, [narrow, open, onClose]);
  return narrow;
}
