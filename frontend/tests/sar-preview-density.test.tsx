import { act, render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { beforeEach, expect, it, vi } from 'vitest';
import { setLocale } from '../src/i18n';
import { StudyOverview } from '../src/features/sar/study/StudyOverview';
import { StudyRegions } from '../src/features/sar/study/StudyRegions';
import { PolicyEditor } from '../src/features/sar/study/PolicyEditor';
import { emptyPolicy } from '../src/features/sar/study/policyDraft';
import { studyContext, studyReport } from './sar-fixtures';

beforeEach(() => setLocale('en'));

it('keeps a known overview rule in recorded-context detail without losing its raw values', async () => {
  const original = JSON.stringify(studyReport);
  render(<StudyOverview report={studyReport} />);
  const rule = screen.getByText('Strong ≤ 10 nM');
  expect(rule).not.toBeVisible();
  const detail = rule.closest('details');
  expect(detail).not.toBeNull();
  expect(detail).not.toHaveAttribute('open');
  await userEvent.click(screen.getByText('Recorded context'));
  expect(rule).toBeVisible();
  await act(() => setLocale('zh-CN'));
  expect(screen.getByText('强活性 ≤ 10 nM')).toBeVisible();
  expect(screen.getByText('IC50 原文 · nM')).toBeVisible();
  expect(JSON.stringify(studyReport)).toBe(original);
});

it('keeps the captured region rule with matching detail and preserves visible comparison results', async () => {
  const original = JSON.stringify(studyReport);
  render(
    <StudyRegions report={studyReport} jobId="study-control" active={false} onRows={vi.fn()} />,
  );
  const rule = screen.getByText('Strong ≤ 10 nM');
  expect(rule).not.toBeVisible();
  expect(rule.closest('details')).not.toHaveAttribute('open');
  expect(screen.getByText('Strong activity 1/1')).toBeVisible();
  expect(screen.getByRole('group', { name: 'Reference-comparison results' })).toBeVisible();
  expect(screen.getByText('Indeterminate')).toBeVisible();
  await userEvent.click(screen.getByText('Matching details'));
  expect(rule).toBeVisible();
  expect(screen.getByText(/Matched 1/)).toBeVisible();
  expect(JSON.stringify(studyReport)).toBe(original);
});

it('does not hide unknown classification or turn it into a measured zero', () => {
  const report = {
    ...studyReport,
    policies: [{ ...studyReport.policies[0]!, strong_threshold: null }],
  };
  render(<StudyOverview report={report} />);
  expect(screen.getByText('Strong activity not classified')).toBeVisible();
  expect(screen.queryByText(/Strong activity 0/)).not.toBeInTheDocument();
});

it('lets the direction control guide an unselected draft but still displays invalid-grade feedback', () => {
  const onChange = vi.fn();
  const { rerender } = render(
    <PolicyEditor context={studyContext} draft={emptyPolicy()} onChange={onChange} />,
  );
  expect(screen.getByLabelText('Activity direction')).toHaveValue('');
  expect(
    screen.queryByText('Confirm direction; source grades must be unique.'),
  ).not.toBeInTheDocument();
  expect(
    screen.getByText('Concentration potency uses the tenth strongest measurement’s decade.'),
  ).toBeVisible();
  rerender(
    <PolicyEditor
      context={studyContext}
      draft={{ ...emptyPolicy(), direction: 'lower', grades: 'A\nA' }}
      onChange={onChange}
    />,
  );
  expect(screen.getByText('Confirm direction; source grades must be unique.')).toBeVisible();
  expect(onChange).not.toHaveBeenCalled();
});
