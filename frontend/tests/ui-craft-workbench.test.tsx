import { readFileSync } from 'node:fs';
import { fireEvent, render, screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it, vi } from 'vitest';
import { api } from '../src/api';
import { ColumnMenu } from '../src/features/results/ColumnMenu';
import { PageCanvas } from '../src/features/pdf/PageCanvas';
import { ResultsTable } from '../src/features/results/ResultsTable';
import { resultColumns } from '../src/model/resultColumns';
import { compound, page } from './fixtures';
import { filterValuesFixture } from './filter-value-fixtures';

const css = (name: string) =>
  readFileSync(new URL('../src/styles/' + name, import.meta.url), 'utf8');
function layer(name: string, selector: string) {
  return Number(css(name).match(new RegExp(selector + '\\s*\\{[^}]*z-index:\\s*(\\d+)'))?.[1]);
}
async function openMenu() {
  vi.spyOn(api, 'filterValues').mockResolvedValue(filterValuesFixture('compound', ['1', '2']));
  vi.spyOn(HTMLElement.prototype, 'getClientRects').mockReturnValue({ length: 1 } as DOMRectList);
  render(
    <ColumnMenu
      projectId="contract"
      column={resultColumns()[1]!}
      onHide={vi.fn()}
      filters={{ q: '', confidence: '', review: '', target: '', page: 1, page_size: 25 }}
      onFilters={vi.fn()}
    />,
  );
  await userEvent.click(screen.getByRole('button', { name: '原文编号 列选项' }));
  const menu = screen.getByRole('dialog', { name: '原文编号 列选项' });
  await within(menu).findByLabelText('筛选值 1');
  return menu;
}
function motionPreference(reduce: boolean) {
  vi.stubGlobal(
    'matchMedia',
    vi.fn(() => ({
      matches: reduce,
      media: '(prefers-reduced-motion: reduce)',
      onchange: null,
      addListener: vi.fn(),
      removeListener: vi.fn(),
      addEventListener: vi.fn(),
      removeEventListener: vi.fn(),
      dispatchEvent: vi.fn(),
    })),
  );
}
const key = 'a'.repeat(64);
const focus = { compoundId: compound.id, key };
const locatedPage = {
  ...page,
  activity_focus: {
    compound_id: compound.id,
    activity_key: key,
    status: 'located' as const,
    boxes: [[10, 20, 40, 50] as [number, number, number, number]],
    message: null,
  },
};

describe('complete workbench interaction craft', () => {
  it('unfreezes phone data cells without losing the header positioning boundary', () => {
    expect(css('responsive.css')).toContain('.results-table td.frozen-structure');
    expect(css('responsive.css')).toContain('.results-table th.frozen-structure');
    expect(css('responsive.css')).not.toMatch(
      /\.results-table \.frozen-structure\s*\{\s*position:\s*static/,
    );
  });
  it('keeps the larger heading target transparent during hover and active states', () => {
    expect(css('table-interactions.css')).toContain('.results-table .column-menu-button:hover');
    expect(css('table-interactions.css')).toContain('.results-table .column-menu-button:active');
  });
  function tableProps() {
    return {
      rows: [compound],
      selected: new Set<string>(),
      focusedId: null,
      onSelect: vi.fn(),
      onSelectPage: vi.fn(),
      onJump: vi.fn(),
      onActivitySource: vi.fn(),
      onCrop: vi.fn(),
      onReview: vi.fn(),
      onHideColumn: vi.fn(),
    };
  }
  it('keeps selection unambiguous without a competing utility menu over the checkbox', () => {
    render(<ResultsTable {...tableProps()} />);
    expect(screen.queryByRole('button', { name: '选择 列选项' })).not.toBeInTheDocument();
    expect(screen.getByRole('checkbox', { name: '选择当前页全部化合物' })).toBeEnabled();
    expect(screen.getByRole('slider', { name: '调整选择列宽' })).toBeEnabled();
    expect(screen.getByRole('button', { name: '原文编号 列选项' })).toBeEnabled();
  });
  it('also respects reduced motion when a source jump focuses its table row', () => {
    motionPreference(true);
    const scroll = vi.spyOn(HTMLElement.prototype, 'scrollIntoView');
    render(<ResultsTable {...tableProps()} focusedId={compound.id} />);
    expect(scroll).toHaveBeenCalledWith({ block: 'nearest', behavior: 'auto' });
  });
  it('places the actual portalled column form above the fullscreen workspace', () => {
    expect(layer('table-interactions.css', '\\.column-menu')).toBeGreaterThan(
      layer('workspace.css', '\\.workspace-layout\\.is-fullscreen'),
    );
  });
  it('keeps reverse Tab inside the open column form and Escape returns to its opener', async () => {
    const menu = await openMenu();
    within(menu).getByRole('button', { name: '升序' }).focus();
    await userEvent.keyboard('{Shift>}{Tab}{/Shift}');
    expect(within(menu).getByRole('button', { name: '隐藏此列' })).toHaveFocus();
    await userEvent.keyboard('{Escape}');
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument();
    expect(screen.getByRole('button', { name: '原文编号 列选项' })).toHaveFocus();
  });
  it('keeps forward Tab inside the open column form', async () => {
    const menu = await openMenu();
    within(menu).getByRole('button', { name: '隐藏此列' }).focus();
    await userEvent.tab();
    expect(within(menu).getByRole('button', { name: '升序' })).toHaveFocus();
  });
  for (const reduce of [true, false])
    it(`respects reduced-motion=${reduce} for real activity source scrolling`, () => {
      motionPreference(reduce);
      const scroll = vi.spyOn(HTMLElement.prototype, 'scrollIntoView');
      render(
        <PageCanvas
          page={locatedPage}
          zoom={1}
          annotations={false}
          selectedId={null}
          onSelect={vi.fn()}
          activityFocus={focus}
        />,
      );
      fireEvent.load(screen.getByRole('img'));
      expect(scroll).toHaveBeenCalledWith({
        block: 'center',
        inline: 'nearest',
        behavior: reduce ? 'auto' : 'smooth',
      });
    });
  it('also respects reduced motion for structure annotations', () => {
    motionPreference(true);
    const scroll = vi.spyOn(HTMLElement.prototype, 'scrollIntoView');
    render(
      <PageCanvas page={page} zoom={1} annotations selectedId={compound.id} onSelect={vi.fn()} />,
    );
    fireEvent.load(screen.getByRole('img'));
    expect(scroll).toHaveBeenCalledWith({ block: 'center', inline: 'nearest', behavior: 'auto' });
  });
});
