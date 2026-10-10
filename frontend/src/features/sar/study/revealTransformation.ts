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
      const selected = reference
        .querySelector('.sar-region-legend button[aria-pressed="true"]')
        ?.closest<HTMLElement>('.sar-reference-map-card');
      if (selected) {
        // Selecting a low legend item can natively pan the graph out of a short
        // viewport. This explicit comparison reveals its own original graph,
        // not the first reference in a multi-source study.
        reference.scrollTo({
          top: Math.max(0, selected.getBoundingClientRect().top - bounds.top + reference.scrollTop),
          behavior,
        });
      }
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
