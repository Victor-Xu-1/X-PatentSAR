import { act, render, screen } from '@testing-library/react';
import { beforeEach, expect, it } from 'vitest';
import { setLocale } from '../src/i18n';
import { StudyPolicyNote, hasStrongRule } from '../src/features/sar/study/StudyPolicyNote';
import { StudyOverview } from '../src/features/sar/study/StudyOverview';
import { studyContext, studyReport } from './sar-fixtures';
import type { ActivityStrengthScale } from '../src/api/types';

beforeEach(() => setLocale('en'));
it('shows automatic tenth-decade limits and refuses to present ambiguous strength as zero', async () => {
  const scale: ActivityStrengthScale = {
    kind: 'numeric',
    direction: 'lower',
    method: 'tenth_decade',
    rule: 'tenth_decade',
    status: 'ready',
    boundary_inclusive: false,
    population: 12,
    eligible: 12,
    excluded: 0,
    distinct: 5,
    anchor_rank: 10,
    anchor_lower: 1,
    anchor_upper: 1,
    anchor_exponent: 0,
    strong_boundary: 10,
    medium_boundary: 100,
  };
  const policy = {
    ...studyReport.policies[0]!,
    strength_method: 'tenth_decade' as const,
    strength_scale: scale,
    strong_threshold: null,
  };
  const { rerender } = render(<StudyPolicyNote policy={policy} context={studyContext} />);
  expect(screen.getByText('Strong <10 nM; medium 10 nM–<100 nM; weak ≥100 nM')).toBeVisible();
  expect(hasStrongRule(policy)).toBe(true);
  await act(() => setLocale('zh-CN'));
  expect(screen.getByText('强 <10 nM；中 10 nM–<100 nM；弱 ≥100 nM')).toBeVisible();
  const unresolved = {
    ...policy,
    strength_scale: {
      ...scale,
      status: 'ambiguous' as const,
      strong_boundary: null,
      medium_boundary: null,
    },
  };
  rerender(<StudyPolicyNote policy={unresolved} context={studyContext} />);
  expect(screen.getByText('第十名数量级不确定，未分档')).toBeVisible();
  expect(hasStrongRule(unresolved)).toBe(false);
});
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
  expect(screen.getByRole('meter', { name: '<10 · Observations' })).toBeVisible();
  expect(screen.queryByText(/Strong activity 0/)).not.toBeInTheDocument();
  expect(hasStrongRule(undefined)).toBe(false);
  expect(hasStrongRule({ ...report.policies[0]!, strong_threshold: 0 })).toBe(true);
});
