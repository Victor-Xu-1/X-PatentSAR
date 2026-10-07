/** Programmatic navigation must obey the same preference as CSS transitions. */
export function preferredScrollBehavior(): ScrollBehavior {
  return window.matchMedia?.('(prefers-reduced-motion: reduce)')?.matches ? 'auto' : 'smooth';
}
