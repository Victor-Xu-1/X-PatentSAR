// Display-only variants of the stock RDKit O/F/Cl colors. Element symbols and
// vector geometry stay unchanged; source SVG and chemistry remain authoritative.
const palette: Readonly<Record<string, string>> = {
  '#FF0000': '#B42318',
  '#33CCCC': '#00695C',
  '#00CC00': '#166534',
};
const readableColor = (value: string) => palette[value.toUpperCase()] ?? value;

/** Called only after the shared passive-SVG validator accepted every element. */
export function improveDrawingContrast(root: Element) {
  for (const element of [root, ...root.querySelectorAll('*')]) {
    for (const name of ['fill', 'stroke']) {
      const color = element.getAttribute(name);
      if (color && palette[color.toUpperCase()]) element.setAttribute(name, readableColor(color));
    }
    const style = element.getAttribute('style');
    if (style)
      element.setAttribute(
        'style',
        style.replace(
          /\b(fill|stroke)(\s*:\s*)(#[\da-f]{6})(?![\da-f])/gi,
          (_entry, property: string, separator: string, color: string) =>
            property + separator + readableColor(color),
        ),
      );
  }
}
