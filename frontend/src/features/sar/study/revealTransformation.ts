import { preferredScrollBehavior } from '../../../model/motion';

/** Reveal one explicitly requested comparison without pushing its reference out of view. */
export function revealTransformation(panel: HTMLElement) {
  const reference = panel
    .closest('.sar-region-explorer')
    ?.querySelector<HTMLElement>('.sar-reference-maps');
  const behavior = preferredScrollBehavior();
  if (reference) {
    const style = getComputedStyle(reference);
    const bounds = reference.getBoundingClientRect();
    const comparison = panel.getBoundingClientRect();
    const explorer = reference.parentElement!.getBoundingClientRect();
    const top = Number.parseFloat(style.top);
    if (
      style.position === 'sticky' &&
      Number.isFinite(top) &&
      bounds.height > 0 &&
      bounds.right < comparison.left
    ) {
      const margin = Number.parseFloat(getComputedStyle(panel).scrollMarginBlockStart) || 0;
      // Sticky layout cannot cross its containing block's bottom. Respect that
      // same boundary when the preview's asynchronous content extends the page.
      window.scrollBy({
        top: Math.min(comparison.top - margin, explorer.bottom - bounds.height - top),
        behavior,
      });
      return;
    }
  }
  panel.scrollIntoView({ block: 'start', behavior });
}
