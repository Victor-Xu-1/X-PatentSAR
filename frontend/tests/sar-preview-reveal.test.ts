import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { revealTransformation } from '../src/features/sar/study/revealTransformation';

function box(top: number, bottom: number, left: number, right: number) {
  return { top, bottom, left, right, height: bottom - top, width: right - left } as DOMRect;
}

function layout({ bottom = 899, position = 'sticky', height = 948, sideBySide = true } = {}) {
  const explorer = document.createElement('div');
  explorer.className = 'sar-region-explorer';
  const reference = document.createElement('section');
  reference.className = 'sar-reference-maps';
  reference.style.position = position;
  reference.style.top = '84px';
  const group = document.createElement('article');
  const preview = document.createElement('section');
  preview.style.scrollMarginBlockStart = '16px';
  group.append(preview);
  explorer.append(reference, group);
  document.body.append(explorer);
  vi.spyOn(explorer, 'getBoundingClientRect').mockReturnValue(box(-600, bottom, 57, 1615));
  vi.spyOn(reference, 'getBoundingClientRect').mockReturnValue(box(-48, height - 48, 57, 709));
  vi.spyOn(preview, 'getBoundingClientRect').mockReturnValue(
    box(234, 828, sideBySide ? 733 : 57, 1615),
  );
  return preview;
}

beforeEach(() => {
  vi.stubGlobal(
    'matchMedia',
    vi.fn(() => ({ matches: true })),
  );
});

afterEach(() => {
  document.querySelectorAll('.sar-region-explorer').forEach((fixture) => fixture.remove());
});

describe('explicit transformation reveal', () => {
  it('repairs the measured tall multi-reference end boundary rather than scrolling the original away', () => {
    const scroll = vi.spyOn(window, 'scrollBy').mockImplementation(() => {});
    const preview = layout();
    const native = vi.spyOn(preview, 'scrollIntoView');
    revealTransformation(preview);
    expect(scroll).toHaveBeenCalledExactlyOnceWith({ top: -133, behavior: 'auto' });
    expect(native).not.toHaveBeenCalled();
  });

  it('uses normal preview alignment when enough fixed-background space remains', () => {
    const scroll = vi.spyOn(window, 'scrollBy').mockImplementation(() => {});
    revealTransformation(layout({ bottom: 2000 }));
    expect(scroll).toHaveBeenCalledExactlyOnceWith({ top: 218, behavior: 'auto' });
  });

  it('derives the limit from the actual short viewport, not a fixed screen height', () => {
    const scroll = vi.spyOn(window, 'scrollBy').mockImplementation(() => {});
    revealTransformation(layout({ height: 488, bottom: 680 }));
    expect(scroll).toHaveBeenCalledExactlyOnceWith({ top: 108, behavior: 'auto' });
  });

  it.each([{ position: 'static' }, { sideBySide: false }, { height: 0 }])(
    'preserves native document flow for a stacked or not-yet-measured reference: %j',
    (options) => {
      const scroll = vi.spyOn(window, 'scrollBy').mockImplementation(() => {});
      const preview = layout(options);
      const native = vi.spyOn(preview, 'scrollIntoView');
      revealTransformation(preview);
      expect(native).toHaveBeenCalledExactlyOnceWith({ block: 'start', behavior: 'auto' });
      expect(scroll).not.toHaveBeenCalled();
    },
  );
});
