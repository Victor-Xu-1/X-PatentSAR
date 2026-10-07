/** Shared keyboard boundary for non-native popups and the fullscreen workspace. */
export function focusableElements(root: ParentNode): HTMLElement[] {
  return Array.from(
    root.querySelectorAll<HTMLElement>(
      'button,input,select,textarea,a[href],summary,iframe,[tabindex]',
    ),
  ).filter(
    (node) =>
      node.tabIndex >= 0 &&
      !node.matches(':disabled') &&
      !node.closest('[inert]') &&
      node.getClientRects().length > 0 &&
      !['hidden', 'collapse'].includes(getComputedStyle(node).visibility),
  );
}

export function containTab(event: KeyboardEvent, root: ParentNode | null) {
  if (event.key !== 'Tab' || !root) return;
  const controls = focusableElements(root);
  const first = controls[0],
    last = controls.at(-1);
  if (event.shiftKey && document.activeElement === first) {
    event.preventDefault();
    last?.focus();
  } else if (!event.shiftKey && document.activeElement === last) {
    event.preventDefault();
    first?.focus();
  }
}
