import { act, render, screen } from '@testing-library/react';
import { beforeEach, expect, it } from 'vitest';
import { setLocale } from '../src/i18n';
import { StudyPolicyNote, hasStrongRule } from '../src/features/sar/study/StudyPolicyNote';
import { StudyOverview } from '../src/features/sar/study/StudyOverview';
import { studyContext, studyReport } from './sar-fixtures';

beforeEach(() => setLocale('en'));
it.each([
  ['lower', true, '≤'],
  ['lower', false, '<'],
  ['higher', true, '≥'],
  ['higher', false, '>'],
] as const)(
  'displays %s inclusive=%s from the captured policy, not inferred patent thresholds',
  (direction, inclusive, relation) => {
    const policy = {
      ...studyReport.policies[0]!,
      direction,
      threshold_inclusive: inclusive,
      strong_threshold: 1,
    };
    const before = JSON.stringify(policy);
    render(<StudyPolicyNote policy={policy} context={studyContext} primary />);
    expect(screen.getByText(`Strong ${relation} 1 nM`)).toBeVisible();
    expect(
      screen.getByText(direction === 'lower' ? 'Lower is stronger' : 'Higher is stronger'),
    ).toBeVisible();
    expect(screen.getByText('IC50 原文 · nM')).toBeVisible();
    expect(JSON.stringify(policy)).toBe(before);
  },
);
it('keeps exact original grade order and raw labels across languages without assigning quantitative thresholds', async () => {
  const policy = {
    ...studyReport.policies[0]!,
    strong_threshold: null,
    grade_order: ['甲', '乙', '丙'],
  };
  render(<StudyPolicyNote policy={policy} context={studyContext} />);
  expect(screen.getByText('Grades, strongest first 甲 → 乙 → 丙')).toBeVisible();
  expect(screen.queryByText(/1 nM/)).not.toBeInTheDocument();
  await act(() => setLocale('zh-CN'));
  expect(screen.getByText('分档从强到弱 甲 → 乙 → 丙')).toBeVisible();
  expect(policy.grade_order).toEqual(['甲', '乙', '丙']);
});
it('does not present unconfigured strength as measured zero or hide actual observations', () => {
  const report = {
    ...studyReport,
    policies: [{ ...studyReport.policies[0]!, strong_threshold: null }],
  };
  render(<StudyOverview report={report} />);
  expect(screen.getByText('Strong activity not classified')).toBeVisible();
  expect(screen.getByText('Observed 2 · Missing 1 · Unresolved 1')).toBeVisible();
  expect(screen.queryByText(/Strong activity 0/)).not.toBeInTheDocument();
  expect(hasStrongRule(undefined)).toBe(false);
  expect(hasStrongRule({ ...report.policies[0]!, strong_threshold: 0 })).toBe(true);
});
