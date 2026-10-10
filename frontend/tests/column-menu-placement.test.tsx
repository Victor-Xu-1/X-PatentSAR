import { fireEvent, render, screen } from '@testing-library/react';
import { expect, it, vi } from 'vitest';
import { ColumnMenu } from '../src/features/results/ColumnMenu';
import { resultColumns } from '../src/model/resultColumns';

it.each([844, 600])(
  'reserves the complete preferred filter area near the bottom of a %spx viewport',
  (height) => {
    vi.stubGlobal('innerHeight', height);
    try {
      render(
        <ColumnMenu
          column={resultColumns().find((column) => column.id === 'compound')!}
          filters={{ q: '', target: '', confidence: '', review: '', page: 1, page_size: 25 }}
          onFilters={vi.fn()}
          onHide={vi.fn()}
        />,
      );
      const button = screen.getByRole('button', { name: /列选项$/ });
      vi.spyOn(button, 'getBoundingClientRect').mockReturnValue(
        new DOMRect(100, height - 100, 100, 30),
      );
      fireEvent.click(button);
      const menu = screen.getByRole('dialog');
      expect(menu.style.top).toBe(Math.max(8, height - 550 - 8) + 'px');
      expect(menu.style.maxHeight).toBe('550px');
      fireEvent.keyDown(document, { key: 'Escape' });
      expect(button).toHaveFocus();
    } finally {
      vi.unstubAllGlobals();
    }
  },
);

it('keeps existing brief-menu placement when no filtering callback exists', () => {
  vi.stubGlobal('innerHeight', 844);
  try {
    render(
      <ColumnMenu
        column={resultColumns().find((column) => column.id === 'structure')!}
        onHide={vi.fn()}
      />,
    );
    const button = screen.getByRole('button', { name: /列选项$/ });
    vi.spyOn(button, 'getBoundingClientRect').mockReturnValue(new DOMRect(100, 744, 100, 30));
    fireEvent.click(button);
    expect(screen.getByRole('dialog').style.top).toBe('444px');
    expect(screen.getByRole('dialog').style.maxHeight).toBe('392px');
  } finally {
    vi.unstubAllGlobals();
  }
});
