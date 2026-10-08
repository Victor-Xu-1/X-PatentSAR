import { UiError } from '../../i18n';
const tags = new Set([
  'svg',
  'g',
  'path',
  'rect',
  'line',
  'polyline',
  'polygon',
  'circle',
  'ellipse',
  'text',
  'tspan',
  'defs',
  'clipPath',
]);
const attributes = new Set([
  'xmlns',
  'xmlns:svg',
  'xmlns:xlink',
  'xmlns:rdkit',
  'version',
  'baseProfile',
  'width',
  'height',
  'viewBox',
  'x',
  'y',
  'x1',
  'x2',
  'y1',
  'y2',
  'rx',
  'ry',
  'cx',
  'cy',
  'r',
  'd',
  'points',
  'id',
  'class',
  'transform',
  'fill',
  'fill-rule',
  'fill-opacity',
  'stroke',
  'stroke-width',
  'stroke-opacity',
  'stroke-linecap',
  'stroke-linejoin',
  'stroke-miterlimit',
  'stroke-dasharray',
  'stroke-dashoffset',
  'opacity',
  'font-size',
  'font-family',
  'font-weight',
  'font-style',
  'text-anchor',
  'style',
  'clip-path',
  'xml:space',
]);
const styleProperties = new Set([
  'fill',
  'fill-rule',
  'fill-opacity',
  'stroke',
  'stroke-width',
  'stroke-opacity',
  'stroke-linecap',
  'stroke-linejoin',
  'stroke-miterlimit',
  'stroke-dasharray',
  'stroke-dashoffset',
  'opacity',
  'font-size',
  'font-family',
  'font-weight',
  'font-style',
  'text-anchor',
]);
function reject(): never {
  throw new UiError('不安全或无效的 SVG，未显示结构。');
}
/** Allow only passive RDKit vector geometry. Never insert server markup into HTML. */
export function safeDrawing(svg: string) {
  if (!svg || svg.length > 1024 * 1024 || /<!DOCTYPE|<!ENTITY|<\?xml-stylesheet/i.test(svg))
    reject();
  const doc = new DOMParser().parseFromString(svg, 'image/svg+xml');
  const root = doc.documentElement;
  if (
    doc.querySelector('parsererror') ||
    root.localName !== 'svg' ||
    root.namespaceURI !== 'http://www.w3.org/2000/svg'
  )
    reject();
  for (const element of [root, ...root.querySelectorAll('*')]) {
    if (element.namespaceURI !== root.namespaceURI || !tags.has(element.localName)) reject();
    for (const attribute of element.attributes) {
      if (
        !attributes.has(attribute.name) ||
        /(?:javascript|data|https?|file):|url\s*\(|expression\s*\(|@|[<>\\]/i.test(attribute.value)
      ) {
        // Namespace declarations name XML vocabularies, not fetchable resources.
        if (
          !attribute.name.startsWith('xmlns') ||
          ![
            'http://www.w3.org/2000/svg',
            'http://www.w3.org/1999/xlink',
            'http://www.rdkit.org/xml',
          ].includes(attribute.value)
        )
          reject();
      }
      if (
        attribute.name === 'style' &&
        attribute.value
          .split(';')
          .filter((s) => s.trim())
          .some((entry) => !styleProperties.has(entry.split(':')[0]?.trim() ?? ''))
      )
        reject();
    }
  }
  // Aspect ratio is pinned to backend geometry; overlay coordinates refer to this same canvas.
  const viewBox = root.getAttribute('viewBox')?.trim().split(/[ ,]+/).map(Number);
  const width = Number(root.getAttribute('width')?.replace(/px$/, ''));
  const height = Number(root.getAttribute('height')?.replace(/px$/, ''));
  const w = viewBox?.length === 4 ? viewBox[2] : width;
  const h = viewBox?.length === 4 ? viewBox[3] : height;
  if (!w || !h || !Number.isFinite(w) || !Number.isFinite(h) || w <= 0 || h <= 0) reject();
  return {
    url: `data:image/svg+xml;charset=utf-8,${encodeURIComponent(new XMLSerializer().serializeToString(root))}`,
    aspectRatio: `${w} / ${h}`,
  };
}
