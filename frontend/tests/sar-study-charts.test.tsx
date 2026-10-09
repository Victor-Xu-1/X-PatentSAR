import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { beforeEach, describe, expect, it } from 'vitest';
import { setLocale } from '../src/i18n';
import { StudyBars } from '../src/features/sar/study/StudyBars';
import {
  chartColor,
  compactBinLabel,
  composition,
} from '../src/features/sar/study/chartPresentation';
import type { StudyBin } from '../src/api/sarStudyTypes';

const bins: StudyBin[] = [
  { label: 'A', kind: 'ordinal', molecules: 1, observations: 3, strong: true },
  { label: 'B', kind: 'ordinal', molecules: 0, observations: 1, strong: false },
  { label: 'missing', kind: 'missing', molecules: 2, observations: 0, strong: false },
];
beforeEach(() => setLocale('en'));
describe('genuine count-driven chart presentation', () => {
  it('separates source-record counts from repeats and retains full raw labels', async () => {
    render(<StudyBars bins={bins} layout="donut" countingContract="unique-molecules-v2" />);
    expect(screen.getByRole('meter', { name: 'A · Source IDs / records' })).toHaveAttribute(
      'value',
      '1',
    );
    expect(screen.getByRole('meter', { name: 'missing · Source IDs / records' })).toHaveAttribute(
      'value',
      '2',
    );
    await userEvent.selectOptions(screen.getByLabelText('Counting unit'), 'observations');
    expect(screen.getByRole('meter', { name: 'A · Observations' })).toHaveAttribute('value', '3');
    expect(composition(bins, 'molecules').total).toBe(3);
    expect(composition(bins, 'observations').total).toBe(4);
  });
  it('uses the same colour semantics for shared bins and keeps unresolved data neutral', () => {
    expect(chartColor(bins[0]!, 0)).toBe('#008c68');
    expect(chartColor(bins[2]!, 2)).toBe('#a8b2ae');
    expect(chartColor({ ...bins[0]!, kind: 'numeric' }, 0, 'lower')).not.toBe(
      chartColor({ ...bins[0]!, kind: 'numeric' }, 0, 'higher'),
    );
    expect(compactBinLabel('[0.1400,125.1225)')).toBe('[0.14, 125.1)');
  });
  it('renders comparative composition without per-fragment unit controls or invented measurements', () => {
    render(
      <StudyBars
        bins={bins}
        layout="stack"
        controlledUnit="molecules"
        countingContract="unique-molecules-v2"
        showLegend={false}
      />,
    );
    expect(screen.queryByRole('combobox')).not.toBeInTheDocument();
    expect(screen.getByRole('graphics-object')).toHaveAttribute('aria-label', 'A: 1 · missing: 2');
    expect(screen.getByText('3')).toBeVisible();
  });
});
