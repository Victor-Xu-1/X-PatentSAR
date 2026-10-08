/** A language choice changes presentation, not a nonmodal edit's lifetime. */
export function isLanguageSelection(target: EventTarget | null): boolean {
  return target instanceof Element && target.closest('[data-interface-language-control]') !== null;
}
