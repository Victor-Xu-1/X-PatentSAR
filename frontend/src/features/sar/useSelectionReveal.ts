import { useEffect, useRef, type RefObject } from 'react';
import { preferredScrollBehavior } from '../../model/motion';

/** Reveal only an explicit reference choice; refresh and locale changes do not replay it. */
export function useSelectionReveal(
  panel: RefObject<HTMLElement | null>,
  canvas: RefObject<HTMLDivElement | null>,
  active: boolean,
  request: number,
  loaded: boolean,
) {
  const revealed = useRef(0);
  const settled = useRef(0);
  useEffect(() => {
    if (!active || !request || revealed.current === request || !panel.current) return;
    revealed.current = request;
    panel.current.focus({ preventScroll: true });
    panel.current.scrollIntoView({ block: 'start', behavior: preferredScrollBehavior() });
  }, [active, request, panel]);
  useEffect(() => {
    if (
      !active ||
      !request ||
      !loaded ||
      revealed.current !== request ||
      settled.current === request
    )
      return;
    settled.current = request;
    // A late drawing response must not pull a user away from a field they started editing.
    if (document.activeElement === panel.current) {
      canvas.current?.scrollIntoView({ block: 'center', behavior: preferredScrollBehavior() });
    }
  }, [active, request, loaded, panel, canvas]);
}
