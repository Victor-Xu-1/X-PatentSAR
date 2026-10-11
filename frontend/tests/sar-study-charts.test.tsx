import { act, render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { beforeEach, describe, expect, it } from 'vitest';
import { setLocale } from '../src/i18n';
import { StudyBars } from '../src/features/sar/study/StudyBars';
import { ChartLegend } from '../src/features/sar/study/StudyComposition';
import { StudyPolicyNote } from '../src/features/sar/study/StudyPolicyNote';
import { studyContext } from './sar-fixtures';
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
  it('shows the actual tenth measurement and decade limits rather than a fifth-rank fallback', () => {
    render(
      <StudyPolicyNote
        context={studyContext}
        policy={{
          context_id: studyContext.id,
          direction: 'lower',
          grade_order: [],
          strong_threshold: null,
          threshold_inclusive: false,
          strength_method: 'tenth_decade',
          strength_scale: {
            kind: 'numeric',
            direction: 'lower',
            rule: 'tenth_decade',
            method: 'tenth_decade',
            status: 'ready',
            eligible: 20,
            excluded: 0,
            distinct: 20,
            boundary_inclusive: false,
            population: 20,
            anchor_rank: 10,
            anchor_lower: 0.56,
            anchor_upper: 0.56,
            anchor_exponent: -1,
            strong_boundary: 1,
            medium_boundary: 10,
          },
        }}
      />,
    );
    expect(screen.getByText('10th strongest: 0.56 nM')).toBeVisible();
    expect(screen.getByText(/Strong <1 nM/)).toBeVisible();
  });
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
    expect(chartColor(bins[2]!, 2)).toBe('#cbd5e1');
    expect(chartColor({ ...bins[0]!, kind: 'numeric' }, 0, 'lower')).not.toBe(
      chartColor({ ...bins[0]!, kind: 'numeric' }, 0, 'higher'),
    );
    expect(compactBinLabel('[0.1400,125.1225)')).toBe('[0.14, 125.1)');
  });
  it('separates all five activity categories and shares the same ring, bar and legend palette', () => {
    const categories = ['strong', 'medium', 'weak', 'unclassified', 'missing'];
    const palette = ['#08a35c', '#a6d86e', '#526170', '#d59a28', '#cbd5e1'];
    const domain: StudyBin[] = categories.map((label) => ({
      label,
      kind: label === 'missing' ? 'missing' : 'strength',
      strong: label === 'strong',
      molecules: 1,
      observations: 2,
    }));
    const original = JSON.stringify(domain);
    render(
      <>
        <StudyBars bins={domain} layout="donut" countingContract="unique-molecules-v2" />
        <ChartLegend bins={domain} />
      </>,
    );
    const rgb = (hex: string) =>
      hex
        .slice(1)
        .match(/../g)!
        .map((value) => parseInt(value, 16));
    for (let index = 0; index < domain.length; index++) {
      const color = palette[index]!;
      expect(chartColor(domain[index]!, index)).toBe(color);
      expect(document.querySelectorAll('.sar-composition-donut circle')[index]).toHaveAttribute(
        'stroke',
        color,
      );
      expect(document.querySelectorAll('.sar-chart-track')[index]).toHaveStyle({ color });
      expect(document.querySelectorAll('.sar-chart-legend li > span')[index]).toHaveStyle({
        background: color,
      });
      for (const other of palette.slice(index + 1))
        expect(Math.hypot(...rgb(color).map((value, n) => value - rgb(other)[n]!))).toBeGreaterThan(
          95,
        );
    }
    expect(JSON.stringify(domain)).toBe(original);
  });
  it('shows the strong percentage beneath the total and follows the actual counting unit and locale', async () => {
    const domain: StudyBin[] = [
      { label: 'strong', kind: 'strength', strong: true, molecules: 6, observations: 10 },
      { label: 'medium', kind: 'strength', strong: false, molecules: 10, observations: 17 },
      { label: 'weak', kind: 'strength', strong: false, molecules: 1, observations: 9 },
      { label: 'missing', kind: 'missing', strong: false, molecules: 2, observations: 2 },
    ];
    render(<StudyBars bins={domain} layout="donut" countingContract="unique-molecules-v2" />);
    expect(document.querySelector('.sar-donut-number')).toHaveTextContent('19');
    expect(document.querySelector('.sar-donut-share')).toHaveTextContent('Strong 31.6%');
    await userEvent.selectOptions(screen.getByLabelText('Counting unit'), 'observations');
    expect(document.querySelector('.sar-donut-number')).toHaveTextContent('38');
    expect(document.querySelector('.sar-donut-share')).toHaveTextContent('Strong 26.3%');
    await act(() => setLocale('zh-CN'));
    expect(document.querySelector('.sar-donut-share')).toHaveTextContent('强活性 26.3%');
    expect(composition(domain, 'molecules').strongPercentage).toBeCloseTo((6 / 19) * 100);
  });
  it('does not invent a percentage for an empty or unclassified measurement domain', () => {
    expect(composition([], 'molecules').strongPercentage).toBeNull();
    expect(composition([{ ...bins[0]!, strong: false }], 'molecules').strongPercentage).toBeNull();
    expect(
      composition(
        [{ label: 'weak', kind: 'strength', strong: false, molecules: 8, observations: 8 }],
        'molecules',
      ).strongPercentage,
    ).toBe(0);
    render(
      <StudyBars
        bins={bins}
        layout="donut"
        strongRule={false}
        countingContract="unique-molecules-v2"
      />,
    );
    expect(document.querySelector('.sar-donut-share')).not.toBeInTheDocument();
    expect(composition([{ ...bins[0]!, strong: false }], 'molecules', true).strongPercentage).toBe(
      0,
    );
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
