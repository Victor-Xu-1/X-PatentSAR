import { expect, it } from 'vitest';
import { safeDrawing } from '../src/features/sar/safeDrawing';
import { render } from '@testing-library/react';
import { createElement } from 'react';
import { RegionMap } from '../src/features/sar/study/RegionMap';
import { namedRegion } from './sar-fixtures';

function documentFor(url: string) {
  return new DOMParser().parseFromString(
    decodeURIComponent(url.split(',').slice(1).join(',')),
    'image/svg+xml',
  );
}
function contrast(color: string) {
  const channels = color
    .slice(1)
    .match(/../g)!
    .map((value) => parseInt(value, 16) / 255)
    .map((value) => (value <= 0.04045 ? value / 12.92 : ((value + 0.055) / 1.055) ** 2.4));
  return 1.05 / (0.2126 * channels[0]! + 0.7152 * channels[1]! + 0.0722 * channels[2]! + 0.05);
}
it('preserves all molecule geometry and labels while increasing exactly the known low-contrast element colors', () => {
  const raw =
    '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 500 350"><path class="bond-1 atom-2" d="M 1,2 L 3,4" style="fill:none;stroke:#33CCCC;stroke-width:1.5"/><text class="atom-2" x="2" y="3" fill="#33cccc">F</text><path class="atom-3" d="M 7,8" style="fill:#00CC00;stroke:none"/><text fill="#FF0000">O</text><text fill="#0000FF">N</text><circle cx="9" cy="8" r="4" fill="#007F66" fill-opacity="0.3"/></svg>';
  const snapshot = raw;
  const image = safeDrawing(raw),
    doc = documentFor(image.url),
    original = new DOMParser().parseFromString(raw, 'image/svg+xml');
  expect(image.aspectRatio).toBe('500 / 350');
  expect(raw).toBe(snapshot);
  const geometry = (document: Document) =>
    [...document.querySelectorAll('*')].map((element) =>
      [...element.attributes]
        .filter((attribute) => !['style', 'fill', 'stroke'].includes(attribute.name))
        .map((attribute) => [attribute.name, attribute.value]),
    );
  expect(geometry(doc)).toEqual(geometry(original));
  expect(doc.querySelector('text')?.textContent).toBe('F');
  expect(doc.querySelector('text')?.getAttribute('fill')).toBe('#00695C');
  expect(doc.querySelector('.atom-3')?.getAttribute('style')).toContain('#166534');
  expect(doc.querySelector('path')?.getAttribute('style')).toContain('stroke:#00695C');
  expect(doc.querySelector('circle')?.getAttribute('fill')).toBe('#007F66');
  expect([...doc.querySelectorAll('text')].at(-1)?.getAttribute('fill')).toBe('#0000FF');
  for (const color of ['#00695C', '#166534', '#B42318'])
    expect(contrast(color)).toBeGreaterThanOrEqual(4.5);
});
it('does not weaken the passive-SVG gate or normalize unsupported colors into accepted markup', () => {
  expect(() =>
    safeDrawing(
      '<svg xmlns="http://www.w3.org/2000/svg" width="10" height="10"><path style="fill:url(https://example.com);stroke:#FF0000"/></svg>',
    ),
  ).toThrow();
  expect(() =>
    safeDrawing('<svg xmlns="http://www.w3.org/2000/svg" width="10" height="10"><script/></svg>'),
  ).toThrow();
  const image = safeDrawing(
    '<svg xmlns="http://www.w3.org/2000/svg" width="10" height="10"><circle r="1" fill="#876543"/></svg>',
  );
  expect(documentFor(image.url).querySelector('circle')?.getAttribute('fill')).toBe('#876543');
});
it('uses neutral readable region labels and preserves color keylines and exact atom coordinates', () => {
  const { container } = render(
    createElement(RegionMap, {
      atoms: [{ index: 0, element: 'C', x: 0.5, y: 0.5 }],
      regions: [{ ...namedRegion, atom_indices: [0] }],
    }),
  );
  expect(container.querySelector('text')?.textContent).toBe('R1');
  expect(container.querySelector('text')?.getAttribute('fill')).toBe('var(--ink)');
  expect(container.querySelector('circle')?.getAttribute('stroke')).toBe('#137e78');
  expect(container.querySelector('circle')?.getAttribute('cx')).toBe('500');
  expect(container.querySelector('circle')?.getAttribute('cy')).toBe('400');
});
